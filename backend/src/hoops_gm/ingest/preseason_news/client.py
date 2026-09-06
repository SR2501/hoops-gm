"""Transport for RotoWire's public NBA news RSS feed.

The feed advertises a ten-minute TTL. Successful captures are cached for that
window, and calls are additionally paced at two seconds in-process. Transport
failures and HTTP 408/425/429/5xx responses receive three bounded attempts.
Other 4xx responses are refusals. Wrong content types, oversized bodies, invalid
XML, and parser drift are non-retryable contract failures. Every successful raw
body is captured; failed bodies are retained under diagnostic endpoint names.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from hoops_gm.ingest.errors import SourceContractError, SourceRejected, SourceUnavailable
from hoops_gm.ingest.preseason_news.models import PreseasonNewsFeed, PreseasonNewsSnapshot
from hoops_gm.ingest.preseason_news.parser import (
    ENDPOINT,
    MAX_BODY_BYTES,
    RSS_URL,
    SOURCE,
    parse_preseason_news,
)
from hoops_gm.ingest.rawstore import RawPayloadStore
from hoops_gm.ingest.retry import RetryPolicy, call_with_retry
from hoops_gm.ingest.throttle import RateLimiter

DEFAULT_MIN_INTERVAL_SECONDS: Final = 2.0
DEFAULT_TIMEOUT_SECONDS: Final = 30.0
DEFAULT_MAX_AGE: Final = timedelta(minutes=10)
_RETRYABLE_STATUS: Final = frozenset({408, 425, 429})
_XML_CONTENT_TYPES: Final = frozenset({"application/xml", "application/rss+xml", "text/xml"})
DEFAULT_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "hoops-gm/0.1 (personal fantasy basketball tool; +https://github.com/SR2501/hoops-gm)"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml",
}


class PreseasonNewsClient:
    """Cached, raw-preserving access to the latest NBA player-news feed."""

    def __init__(
        self,
        *,
        store: RawPayloadStore | None = None,
        limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        headers: dict[str, str] | None = None,
        opener: Any = None,
    ) -> None:
        self.store = store
        self.limiter = limiter or RateLimiter(DEFAULT_MIN_INTERVAL_SECONDS)
        self.retry_policy = retry_policy or RetryPolicy()
        self.timeout_seconds = timeout_seconds
        self.headers = dict(DEFAULT_HEADERS if headers is None else headers)
        self._opener = opener or urllib.request.urlopen

    def latest(self, *, max_age: timedelta | None = None) -> PreseasonNewsSnapshot:
        """Fetch, parse, and identify the exact source bytes used."""
        params = {"url": RSS_URL}
        window = DEFAULT_MAX_AGE if max_age is None else max_age
        if self.store is not None:
            cached = self.store.fresh(
                source=SOURCE,
                endpoint=ENDPOINT,
                params=params,
                max_age=window,
            )
            if cached is not None:
                body = cached.read_bytes()
                return PreseasonNewsSnapshot(
                    feed=parse_preseason_news(body, observed_at=cached.fetched_at),
                    observed_at=cached.fetched_at,
                    source_payload_sha256=cached.sha256(),
                )

        body, status, content_type = call_with_retry(self._request, policy=self.retry_policy)
        observed_at = datetime.now(UTC)
        try:
            feed = self._parse_response(body, content_type=content_type, observed_at=observed_at)
        except SourceContractError:
            self._capture_failed(
                kind="contract_error",
                body=body,
                status=status,
                content_type=content_type,
            )
            raise

        digest = hashlib.sha256(body).hexdigest()
        if self.store is not None:
            capture = self.store.put(
                source=SOURCE,
                endpoint=ENDPOINT,
                params=params,
                body=body,
                http_status=status,
                content_type=content_type,
                fetched_at=observed_at,
            )
            digest = capture.sha256()
            observed_at = capture.fetched_at
        return PreseasonNewsSnapshot(
            feed=feed,
            observed_at=observed_at,
            source_payload_sha256=digest,
        )

    def _request(self) -> tuple[bytes, int, str | None]:
        request = urllib.request.Request(RSS_URL, headers=dict(self.headers))
        self.limiter.acquire()
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                body = response.read(MAX_BODY_BYTES + 1)
                status = int(getattr(response, "status", 200))
                content_type = response.headers.get("Content-Type")
        except urllib.error.HTTPError as exc:
            body, body_was_truncated = _read_error_body(exc)
            self._capture_failed(
                kind="http_error_incomplete_read" if body_was_truncated else "http_error",
                body=body,
                status=exc.code,
                content_type=exc.headers.get("Content-Type") if exc.headers is not None else None,
            )
            if _is_retryable_status(exc.code):
                raise SourceUnavailable(
                    f"HTTP {exc.code}",
                    source=SOURCE,
                    endpoint=ENDPOINT,
                    detail=body[:400],
                    status_code=exc.code,
                ) from exc
            raise SourceRejected(
                f"HTTP {exc.code}",
                source=SOURCE,
                endpoint=ENDPOINT,
                detail=body[:400],
                status_code=exc.code,
            ) from exc
        except http.client.IncompleteRead as exc:
            partial = bytes(exc.partial)
            self._capture_failed(
                kind="incomplete_read",
                body=partial,
                status=None,
                content_type=None,
            )
            raise SourceUnavailable(
                "response body was truncated",
                source=SOURCE,
                endpoint=ENDPOINT,
                detail={
                    "partial_body_sha256": hashlib.sha256(partial).hexdigest(),
                    "partial_byte_size": len(partial),
                },
            ) from exc
        except urllib.error.URLError as exc:
            raise SourceUnavailable(
                f"could not reach the source: {exc.reason}",
                source=SOURCE,
                endpoint=ENDPOINT,
            ) from exc
        except http.client.HTTPException as exc:
            raise SourceUnavailable(
                f"HTTP protocol failure: {exc}",
                source=SOURCE,
                endpoint=ENDPOINT,
            ) from exc
        except TimeoutError as exc:
            raise SourceUnavailable(
                f"timed out after {self.timeout_seconds}s",
                source=SOURCE,
                endpoint=ENDPOINT,
            ) from exc
        except OSError as exc:
            raise SourceUnavailable(
                f"transport failure: {exc}",
                source=SOURCE,
                endpoint=ENDPOINT,
            ) from exc

        if len(body) > MAX_BODY_BYTES:
            self._capture_failed(
                kind="contract_error",
                body=body,
                status=status,
                content_type=content_type,
            )
            raise SourceContractError(
                f"response exceeded the {MAX_BODY_BYTES}-byte limit",
                source=SOURCE,
                endpoint=ENDPOINT,
                detail={"captured_prefix_sha256": hashlib.sha256(body).hexdigest()},
            )
        if status >= 400:
            self._capture_failed(
                kind="http_error",
                body=body,
                status=status,
                content_type=content_type,
            )
            if _is_retryable_status(status):
                raise SourceUnavailable(
                    f"HTTP {status}",
                    source=SOURCE,
                    endpoint=ENDPOINT,
                    detail=body[:400],
                    status_code=status,
                )
            raise SourceRejected(
                f"HTTP {status}",
                source=SOURCE,
                endpoint=ENDPOINT,
                detail=body[:400],
                status_code=status,
            )
        return body, status, content_type

    @staticmethod
    def _parse_response(
        body: bytes, *, content_type: str | None, observed_at: datetime
    ) -> PreseasonNewsFeed:
        media_type = (content_type or "").partition(";")[0].strip().lower()
        if media_type not in _XML_CONTENT_TYPES:
            raise SourceContractError(
                f"response Content-Type changed to {content_type!r}",
                source=SOURCE,
                endpoint=ENDPOINT,
            )
        return parse_preseason_news(body, observed_at=observed_at)

    def _capture_failed(
        self,
        *,
        kind: str,
        body: bytes,
        status: int | None,
        content_type: str | None,
    ) -> None:
        if self.store is None:
            return
        self.store.put(
            source=SOURCE,
            endpoint=f"{ENDPOINT}.{kind}",
            params={"url": RSS_URL},
            body=body,
            http_status=status,
            content_type=content_type,
        )


def _read_error_body(exc: urllib.error.HTTPError) -> tuple[bytes, bool]:
    try:
        return exc.read(MAX_BODY_BYTES + 1), False
    except http.client.IncompleteRead as read_error:
        return bytes(read_error.partial), True
    except (OSError, http.client.HTTPException):
        return b"", False
    finally:
        with contextlib.suppress(Exception):
            exc.close()


def _is_retryable_status(status: int) -> bool:
    return status in _RETRYABLE_STATUS or 500 <= status <= 599
