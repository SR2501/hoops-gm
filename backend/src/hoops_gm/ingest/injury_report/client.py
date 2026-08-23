"""Transport for the NBA official injury report PDF.

Documented behaviour of this source, established by fetching it live on
2026-08-17 rather than by reading any specification — none is published:

Where it lives
    ``https://ak-static.cms.nba.com/referee/injury/Injury-Report_<date>_<time>.pdf``.
    Not ``stats.nba.com`` and not ``nba_api``: this is a static document on the
    NBA's CMS CDN, fetched with a plain HTTP client rather than the library
    R27 requires for the stats host.

Filename format, two eras
    Verified live against archived 2025-26 season reports: a report from
    2025-11-01 05:30 PM ET is ``Injury-Report_2025-11-01_05PM.pdf`` (hourly,
    on the hour), while one from 2026-01-15 05:30 PM ET is
    ``Injury-Report_2026-01-15_05_30PM.pdf`` (15-minute granularity). The
    boundary is 2025-12-22 00:00 ET. The NBA has changed this filename format
    before, without notice, and may again for 2026-27 — that risk is exactly
    what the live smoke test exists to catch; nothing here can protect
    against it in advance.

Throttling
    One request every two seconds. Nothing here needs to be fast — a report
    is checked at most a handful of times a day — and this is an undocumented
    CDN path, not a published API, so the same politeness Fantrax gets
    applies here for the same reason.

Retry
    Three attempts with exponential backoff, **only** on
    :class:`~hoops_gm.ingest.errors.SourceUnavailable`.

When a report has not been published for the requested timestamp
    **Both HTTP 404 and HTTP 403 are normal, not a contract violation** —
    verified live 2026-08-17: an in-season historical timestamp returns 404,
    while a pre-season date (2025-08-15, months before any report existed)
    returns **403**, not 404. This CDN does not distinguish "you may not have
    this" from "this was never here"; both mean the same thing for a report
    path, and both become :class:`ReportNotAvailable`, a
    :class:`~hoops_gm.ingest.errors.SourceRejected` subtype a caller is
    expected to catch and treat as "try a different timestamp" rather than as
    upstream drift. Reports are published at irregular times through the day
    (evening-before, then game-day updates), so most arbitrary timestamps
    have no report at all — this is the ordinary case, not the exception.

When the source is down
    A timeout, connection error or 5xx becomes ``SourceUnavailable`` and is
    retried.

When the source returns garbage
    A 200 response whose body does not start with the PDF magic number
    (``%PDF-``) becomes :class:`~hoops_gm.ingest.errors.SourceContractError`
    immediately, before spending time inside a PDF parser on a body that was
    never a PDF at all — an HTML error page served with a 200, for instance.
"""

from __future__ import annotations

import contextlib
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from hoops_gm.ingest.errors import SourceContractError, SourceRejected, SourceUnavailable
from hoops_gm.ingest.injury_report.parser import ENDPOINT, SOURCE
from hoops_gm.ingest.rawstore import RawPayloadStore
from hoops_gm.ingest.retry import RetryPolicy, call_with_retry
from hoops_gm.ingest.throttle import RateLimiter

URL_TEMPLATE: Final = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{date}_{time}.pdf"
EASTERN: Final = ZoneInfo("America/New_York")

#: Verified live 2026-08-17: the last confirmed hourly-format filename and the
#: first confirmed 15-minute-format one straddle this instant. Format eras,
#: not a claim about when reports were actually published. Public (not
#: module-private) because ``injury_report.backfill`` needs the same
#: boundary to choose its candidate-generation strategy — see
#: :func:`is_fifteen_minute_era`.
#:
#: The boundary is **midnight Eastern**, which leaves one window where an
#: off-by-one would be invisible in aggregate: reports filed *on* 2025-12-22
#: between midnight and that day's first tip-off. Previously reasoned, not
#: verified. **Settled 2026-08-24 against all 582 cached reports**, and the
#: window turns out to be not merely non-empty but to contain *every* report
#: filed that day — all four, at 16:30 / 17:30 / 18:15 / 18:45 Eastern against
#: a 19:00 Eastern first tip-off. Two independent signatures both classify
#: them as new-era, neither of which consults this constant:
#:
#: 1. **Minute-of-hour.** Across the 121 legacy-era timestamps the minute is
#:    only ever ``:30`` (116) or ``:45`` (5) — ``:15`` and ``:00`` occur zero
#:    times. The boundary date's 18:15 report carries a ``:15``, a minute the
#:    legacy era never once produced.
#: 2. **Lead-time cadence.** Those four sit at 150 / 90 / 45 / 15 minutes
#:    before first tip — the new era's converging pre-tip ladder. The legacy
#:    day before ran 18:45 and 22:45 Eastern against a 15:30 first tip, i.e.
#:    *after* it, which is a different regime entirely.
#:
#: Grouping that evidence by Eastern date rather than UTC date matters and was
#: checked both ways: 7 timestamps in the corpus have a UTC date one day ahead
#: of their Eastern date (late reports at ``00:15``/``00:45`` UTC). None fall
#: near this boundary, so the classification is unaffected — but anything that
#: buckets reports *by day* should read that as a live hazard rather than a
#: near miss.
FIFTEEN_MINUTE_ERA_START: Final = datetime(2025, 12, 22, 0, 0, tzinfo=EASTERN)
_STRF_LEGACY: Final = "%I%p"
_STRF_NEW: Final = "%I_%M%p"

DEFAULT_MIN_INTERVAL_SECONDS: Final = 2.0
DEFAULT_TIMEOUT_SECONDS: Final = 30.0
#: A published report is immutable once captured — the URL itself names the
#: exact timestamp — so a prior capture is reused forever, the same reasoning
#: as a completed game's box score.
DEFAULT_MAX_AGE: Final = timedelta(days=3650)

#: Status codes that mean "come back later" rather than "this timestamp has
#: no report" or "you are wrong".
_RETRYABLE_STATUS: Final = frozenset({408, 425, 429, 500, 502, 503, 504})

DEFAULT_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "hoops-gm/0.1 (personal fantasy basketball tool; "
        "+https://github.com/SR2501/hoops-gm) python-urllib"
    ),
    "Accept": "application/pdf,*/*",
}

_PDF_MAGIC: Final = b"%PDF-"


class ReportNotAvailable(SourceRejected):
    """No report has been published for the requested timestamp yet.

    Refines :class:`~hoops_gm.ingest.errors.SourceRejected` because this is
    the ordinary, expected case for the vast majority of timestamps a caller
    might ask about — reports are published irregularly through the day, not
    on every 5- or 15-minute mark — and a caller needs to tell it apart from
    a genuine schema break without inspecting an HTTP status code itself.
    Raised for both HTTP 404 and HTTP 403: this CDN answers a pre-season
    date, months before any report existed, with 403 rather than 404
    (verified live 2026-08-17), so both codes mean the same thing here.

    ``status_code`` is still recorded (404 or 403) rather than discarded,
    because the two are not equally trustworthy across *many* consecutive
    requests: a lone 403 for a pre-season or off-cadence timestamp is the
    same "not published" signal as a 404, but a long *run* of 403s where
    reports were expected is also exactly what a WAF block or a rate-limit
    response disguised as a client error would look like. A caller doing a
    bounded historical backfill is better served treating a 403 *streak* as
    suspicious and aborting loudly than recording dozens of them as ordinary
    absence — see ``injury_report.backfill``'s streak guard.
    """


def is_fifteen_minute_era(instant: datetime) -> bool:
    """Whether ``instant`` falls in the 15-minute-filename URL era.

    ``instant`` must be timezone-aware; compared in Eastern, the wall clock
    the boundary itself is defined in. Exposed so a caller choosing *how* to
    guess a candidate report timestamp (not merely how to build a URL for
    one already chosen) can branch on the same boundary this transport uses,
    rather than re-deriving or duplicating the cutoff date.
    """
    if instant.tzinfo is None:
        raise ValueError("instant must be timezone-aware")
    return instant.astimezone(EASTERN) >= FIFTEEN_MINUTE_ERA_START


def report_url(report_timestamp: datetime) -> str:
    """Build the PDF URL for a report timestamp.

    ``report_timestamp`` must be timezone-aware; it is converted to the
    Eastern wall clock the report's own filenames are always expressed in.

    **Exact-minute match in the 15-minute era, no drift tolerance.** Unlike
    the legacy era (which always truncates to the hour, so any request in
    that hour resolves to the same file), a 15-minute-era request is not
    rounded to the nearest quarter-hour here — it is formatted verbatim. A
    request for ``13:07`` asks for ``..._01_07PM.pdf``, which almost
    certainly does not exist if the source only ever publishes on the
    quarter-hour; only a request for a minute the source actually published
    at succeeds. The parser's separate 45-minutes-of-drift tolerance (see
    ``parser._verify_masthead``) is a *post-fetch* sanity check against
    whichever file this exact URL named — it cannot recover a URL that 404s
    before any body is read, and does not make this function's own minute
    choice more forgiving.
    """
    if report_timestamp.tzinfo is None:
        raise ValueError("report_timestamp must be timezone-aware")
    eastern = report_timestamp.astimezone(EASTERN)
    date_part = eastern.strftime("%Y-%m-%d")
    if is_fifteen_minute_era(eastern):
        time_part = eastern.strftime(_STRF_NEW)
    else:
        # Legacy filenames are always on the hour; verified live against
        # 2025-11-01 05PM (not 05_00PM) for a report requested at 05:30 ET.
        time_part = eastern.replace(minute=0).strftime(_STRF_LEGACY)
    return URL_TEMPLATE.format(date=date_part, time=time_part)


@dataclass
class InjuryReportClient:
    """Fetches the raw injury report PDF, capturing every response.

    Parsing is deliberately not this class's job — see
    :mod:`hoops_gm.ingest.injury_report.parser` — so a contract test can
    exercise the parser against a captured fixture with no network at all.
    """

    store: RawPayloadStore | None = None
    limiter: RateLimiter | None = None
    retry_policy: RetryPolicy | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    headers: dict[str, str] | None = None
    #: Injectable so a test can drive the transport without a network.
    opener: Any = None

    def __post_init__(self) -> None:
        self.limiter = self.limiter or RateLimiter(DEFAULT_MIN_INTERVAL_SECONDS)
        self.retry_policy = self.retry_policy or RetryPolicy()
        self.headers = dict(DEFAULT_HEADERS if self.headers is None else self.headers)
        self.opener = self.opener or urllib.request.urlopen

    def fetch(self, report_timestamp: datetime, *, max_age: timedelta | None = None) -> bytes:
        """Fetch the raw PDF bytes for a report timestamp.

        Raises :class:`ReportNotAvailable` for an HTTP 404 rather than
        returning ``None`` or an empty document, so a caller cannot mistake
        "not published yet" for "an empty, valid report".
        """
        url = report_url(report_timestamp)
        window = DEFAULT_MAX_AGE if max_age is None else max_age
        params = {"url": url}

        if self.store is not None:
            cached = self.store.fresh(
                source=SOURCE, endpoint=ENDPOINT, params=params, max_age=window
            )
            if cached is not None:
                return cached.read_bytes()

        body, status, content_type = call_with_retry(
            lambda: self._request(url), policy=self.retry_policy
        )

        if not body.startswith(_PDF_MAGIC):
            raise SourceContractError(
                f"response for {url} did not start with the PDF magic number; "
                "the source may have returned an HTML error page under HTTP 200",
                source=SOURCE,
                endpoint=ENDPOINT,
                detail=body[:200],
            )

        if self.store is not None:
            self.store.put(
                source=SOURCE,
                endpoint=ENDPOINT,
                params=params,
                body=body,
                http_status=status,
                content_type=content_type,
            )
        return body

    def _request(self, url: str) -> tuple[bytes, int, str | None]:
        request = urllib.request.Request(url, headers=dict(self.headers or {}))
        assert self.limiter is not None  # set in __post_init__
        self.limiter.acquire()
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                return (
                    response.read(),
                    getattr(response, "status", 200),
                    response.headers.get("Content-Type"),
                )
        except urllib.error.HTTPError as exc:
            body = _read_error_body(exc)
            if exc.code in (403, 404):
                raise ReportNotAvailable(
                    f"no report published for this timestamp (HTTP {exc.code}): {url}",
                    source=SOURCE,
                    endpoint=ENDPOINT,
                    status_code=exc.code,
                ) from exc
            if exc.code in _RETRYABLE_STATUS:
                raise SourceUnavailable(
                    f"HTTP {exc.code}", source=SOURCE, endpoint=ENDPOINT, detail=body[:400]
                ) from exc
            raise SourceRejected(
                f"HTTP {exc.code}", source=SOURCE, endpoint=ENDPOINT, detail=body[:400]
            ) from exc
        except urllib.error.URLError as exc:
            raise SourceUnavailable(
                f"could not reach the source: {exc.reason}", source=SOURCE, endpoint=ENDPOINT
            ) from exc
        except TimeoutError as exc:
            raise SourceUnavailable(
                f"timed out after {self.timeout_seconds}s", source=SOURCE, endpoint=ENDPOINT
            ) from exc
        except OSError as exc:
            raise SourceUnavailable(
                f"transport failure: {exc}", source=SOURCE, endpoint=ENDPOINT
            ) from exc


def _read_error_body(exc: urllib.error.HTTPError) -> bytes:
    try:
        return exc.read()
    except Exception:  # diagnostic only
        return b""
    finally:
        with contextlib.suppress(Exception):
            exc.close()
