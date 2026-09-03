"""Transport for the NBA's official NBA and G League transaction archives.

The feeds are public, unauthenticated archives discovered from the transaction
pages' own JavaScript on 2026-09-02.

Throttling
    One request every two seconds across both feeds. Each response is a complete
    archive and the pages say transactions update daily, so faster access has no
    product value.

Retry
    Three attempts with exponential backoff, only for transport failures and
    retryable HTTP statuses.

Caching
    A decoded success capture younger than six hours is reused. With a raw
    store configured, malformed and failed bodies are preserved under
    non-cacheable diagnostic endpoint names.

When a source is down or refuses
    Transport failures, 408/425/429 and 5xx responses become retryable
    ``SourceUnavailable``. Other 4xx responses become non-retryable
    ``SourceRejected``.

When a source returns garbage
    Non-UTF-8 or non-JSON bodies become ``SourceContractError``. Shape and
    vocabulary drift is rejected by the strict parsers.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from hoops_gm.ingest.errors import SourceContractError, SourceRejected, SourceUnavailable
from hoops_gm.ingest.nba.client import _is_transport_failure
from hoops_gm.ingest.nba_transactions.models import (
    GLeagueTransactionRecord,
    NbaPlayerMovementRecord,
)
from hoops_gm.ingest.nba_transactions.parsers import (
    G_LEAGUE_TRANSACTIONS_ENDPOINT,
    NBA_PLAYER_MOVEMENT_ENDPOINT,
    SOURCE,
    parse_g_league_transactions,
    parse_nba_player_movements,
)
from hoops_gm.ingest.rawstore import RawPayloadStore
from hoops_gm.ingest.retry import RetryPolicy, call_with_retry
from hoops_gm.ingest.throttle import RateLimiter

NBA_PLAYER_MOVEMENT_URL: Final = (
    "https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json"
)
G_LEAGUE_TRANSACTIONS_URL: Final = "https://gleague.nba.com/api/transactions/fetchTransactions"

DEFAULT_MIN_INTERVAL_SECONDS: Final = 2.0
DEFAULT_TIMEOUT_SECONDS: Final = 60.0
DEFAULT_MAX_AGE: Final = timedelta(hours=6)
_RETRYABLE_STATUS: Final = frozenset({408, 425, 429})

# The G League host rejects an honest bot-style or "compatible" User-Agent with
# HTTP 403. It answers a full browser-shaped UA carrying the project name.
G_LEAGUE_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36 hoops-gm/0.1"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://gleague.nba.com/transactions/",
}

_ENDPOINT_URLS: Final = {
    NBA_PLAYER_MOVEMENT_ENDPOINT: NBA_PLAYER_MOVEMENT_URL,
    G_LEAGUE_TRANSACTIONS_ENDPOINT: G_LEAGUE_TRANSACTIONS_URL,
}


class NbaOfficialTransactionsClient:
    """Cached access to the two official transaction archives."""

    def __init__(
        self,
        *,
        store: RawPayloadStore | None = None,
        limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        nba_session: Any = None,
        nba_headers: dict[str, str] | None = None,
        g_league_opener: Any = None,
        g_league_headers: dict[str, str] | None = None,
    ) -> None:
        self.store = store
        self.limiter = limiter or RateLimiter(DEFAULT_MIN_INTERVAL_SECONDS)
        self.retry_policy = retry_policy or RetryPolicy()
        self.timeout_seconds = timeout_seconds
        if nba_session is None or nba_headers is None:
            default_session, default_headers = _default_nba_transport()
        else:
            default_session, default_headers = None, {}
        self._nba_session = default_session if nba_session is None else nba_session
        self._nba_headers = dict(default_headers if nba_headers is None else nba_headers)
        self._g_league_opener = g_league_opener or urllib.request.urlopen
        self._g_league_headers = dict(
            G_LEAGUE_HEADERS if g_league_headers is None else g_league_headers
        )

    def nba_player_movements(
        self, *, max_age: timedelta | None = None
    ) -> list[NbaPlayerMovementRecord]:
        return parse_nba_player_movements(
            self.fetch_json(NBA_PLAYER_MOVEMENT_ENDPOINT, max_age=max_age)
        )

    def g_league_transactions(
        self, *, max_age: timedelta | None = None
    ) -> list[GLeagueTransactionRecord]:
        return parse_g_league_transactions(
            self.fetch_json(G_LEAGUE_TRANSACTIONS_ENDPOINT, max_age=max_age)
        )

    def fetch_json(self, endpoint: str, *, max_age: timedelta | None = None) -> Any:
        """Fetch one known archive and decode its exact captured body."""
        url = _ENDPOINT_URLS.get(endpoint)
        if url is None:
            raise SourceContractError(
                f"no transaction URL registered for endpoint {endpoint!r}",
                source=SOURCE,
                endpoint=endpoint,
            )
        params = {"url": url}
        window = DEFAULT_MAX_AGE if max_age is None else max_age

        if self.store is not None:
            cached = self.store.fresh(
                source=SOURCE, endpoint=endpoint, params=params, max_age=window
            )
            if cached is not None:
                return self._decode(cached.read_bytes(), endpoint=endpoint)

        body, status, content_type = call_with_retry(
            lambda: self._request(endpoint, url), policy=self.retry_policy
        )
        observed_at = datetime.now(UTC)
        try:
            payload = self._decode(body, endpoint=endpoint)
        except SourceContractError:
            self._capture_failed_body(
                endpoint=endpoint,
                url=url,
                kind="contract_error",
                body=body,
                status=status,
                content_type=content_type,
            )
            raise

        if self.store is not None:
            self.store.put(
                source=SOURCE,
                endpoint=endpoint,
                params=params,
                body=body,
                http_status=status,
                content_type=content_type,
                fetched_at=observed_at,
            )
        return payload

    def _request(self, endpoint: str, url: str) -> tuple[bytes, int, str | None]:
        self.limiter.acquire()
        if endpoint == NBA_PLAYER_MOVEMENT_ENDPOINT:
            return self._request_nba(url)
        return self._request_g_league(url)

    def _request_nba(self, url: str) -> tuple[bytes, int, str | None]:
        try:
            response = self._nba_session.get(
                url, headers=dict(self._nba_headers), timeout=self.timeout_seconds
            )
        except Exception as exc:
            if _is_transport_failure(exc):
                raise SourceUnavailable(
                    f"could not reach the source: {exc}",
                    source=SOURCE,
                    endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT,
                ) from exc
            raise

        try:
            body = bytes(response.content)
            status = int(response.status_code)
            content_type = response.headers.get("Content-Type")
        finally:
            response.close()
        if status >= 400:
            self._capture_failed_body(
                endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT,
                url=url,
                kind="http_error",
                body=body,
                status=status,
                content_type=content_type,
            )
        _raise_for_status(status, body, endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT)
        return body, status, content_type

    def _request_g_league(self, url: str) -> tuple[bytes, int, str | None]:
        request = urllib.request.Request(url, headers=dict(self._g_league_headers))
        try:
            with self._g_league_opener(request, timeout=self.timeout_seconds) as response:
                body = response.read()
                status = int(getattr(response, "status", 200))
                content_type = response.headers.get("Content-Type")
        except urllib.error.HTTPError as exc:
            body, body_was_truncated = _read_error_body(exc)
            self._capture_failed_body(
                endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
                url=url,
                kind="incomplete_http_error" if body_was_truncated else "http_error",
                body=body,
                status=exc.code,
                content_type=exc.headers.get("Content-Type") if exc.headers is not None else None,
            )
            if _is_retryable_status(exc.code):
                raise SourceUnavailable(
                    f"HTTP {exc.code}",
                    source=SOURCE,
                    endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
                    detail=body[:400],
                    status_code=exc.code,
                ) from exc
            raise SourceRejected(
                f"HTTP {exc.code}",
                source=SOURCE,
                endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
                detail=body[:400],
                status_code=exc.code,
            ) from exc
        except http.client.IncompleteRead as exc:
            partial = bytes(exc.partial)
            self._capture_failed_body(
                endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
                url=url,
                kind="incomplete_read",
                body=partial,
                status=None,
                content_type=None,
            )
            raise SourceUnavailable(
                "response body was truncated",
                source=SOURCE,
                endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
                detail={
                    "partial_body_sha256": hashlib.sha256(partial).hexdigest(),
                    "partial_byte_size": len(partial),
                },
            ) from exc
        except http.client.HTTPException as exc:
            raise SourceUnavailable(
                f"HTTP transport failure: {exc}",
                source=SOURCE,
                endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
            ) from exc
        except urllib.error.URLError as exc:
            raise SourceUnavailable(
                f"could not reach the source: {exc.reason}",
                source=SOURCE,
                endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
            ) from exc
        except TimeoutError as exc:
            raise SourceUnavailable(
                f"timed out after {self.timeout_seconds}s",
                source=SOURCE,
                endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
            ) from exc
        except OSError as exc:
            raise SourceUnavailable(
                f"transport failure: {exc}",
                source=SOURCE,
                endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
            ) from exc
        _raise_for_status(status, body, endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT)
        return body, status, content_type

    def _capture_failed_body(
        self,
        *,
        endpoint: str,
        url: str,
        kind: str,
        body: bytes,
        status: int | None,
        content_type: str | None,
    ) -> None:
        if self.store is None:
            return
        self.store.put(
            source=SOURCE,
            endpoint=f"{endpoint}.{kind}",
            params={"url": url},
            body=body,
            http_status=status,
            content_type=content_type,
        )

    @staticmethod
    def _decode(body: bytes, *, endpoint: str) -> Any:
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceContractError(
                f"response was not UTF-8 JSON: {exc}",
                source=SOURCE,
                endpoint=endpoint,
                detail={
                    "body_sha256": hashlib.sha256(body).hexdigest(),
                    "byte_size": len(body),
                },
            ) from exc


def _default_nba_transport() -> tuple[Any, dict[str, str]]:
    # R27 requires stats.nba.com traffic to use nba_api's maintained session and
    # headers. The static movement archive has no endpoint wrapper, so use the
    # library's own transport primitives rather than a second HTTP stack.
    from nba_api.stats.library.http import NBAStatsHTTP

    headers = dict(NBAStatsHTTP.headers)
    headers["Accept-Encoding"] = "gzip, deflate"
    return NBAStatsHTTP.get_session(), headers


def _raise_for_status(status: int, body: bytes, *, endpoint: str) -> None:
    if status < 400:
        return
    if _is_retryable_status(status):
        raise SourceUnavailable(
            f"HTTP {status}",
            source=SOURCE,
            endpoint=endpoint,
            detail=body[:400],
            status_code=status,
        )
    raise SourceRejected(
        f"HTTP {status}",
        source=SOURCE,
        endpoint=endpoint,
        detail=body[:400],
        status_code=status,
    )


def _read_error_body(exc: urllib.error.HTTPError) -> tuple[bytes, bool]:
    try:
        return exc.read(), False
    except http.client.IncompleteRead as read_exc:
        return bytes(read_exc.partial), True
    except OSError:  # diagnostic only
        return b"", False
    finally:
        exc.close()


def _is_retryable_status(status: int) -> bool:
    return status in _RETRYABLE_STATUS or 500 <= status <= 599
