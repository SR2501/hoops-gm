"""HTTP transport for the Fantrax official ``/fxea/general/`` API.

Documented behaviour of this source, all established by hitting it on
2026-08-17 rather than by reading its beta documentation:

Throttling
    Read-only, low frequency, no published rate limit. Paced at one request
    every two seconds — half the rate used for ``stats.nba.com`` — because
    nothing here needs to be fast (a player-id map and an ADP list change
    daily at most) and being conspicuously polite to an undocumented beta
    endpoint costs us nothing.

Retry
    Three attempts with exponential backoff, and **only** on
    :class:`SourceUnavailable`. A refusal and a schema change are not retried;
    see :mod:`hoops_gm.ingest.errors` for why.

Authentication
    ``getPlayerIds`` and ``getAdp`` need none — verified. ``getLeagueInfo`` needs
    a ``leagueId``; the target private league returned its settings without a
    ``userSecretId`` on 2026-08-18. A secret remains optional for endpoints or
    leagues that reject the unauthenticated request.

When the source is down
    A timeout, a connection error or a 5xx becomes ``SourceUnavailable`` and is
    retried. Exhausted retries propagate — the caller decides whether a stale
    cached capture is acceptable, because that judgement depends on what the
    data is for. Nothing here silently substitutes old data for new.

When the source returns garbage
    Three separate cases, deliberately not collapsed together:

    * a body that is not JSON becomes ``SourceContractError``;
    * a body that is JSON and is Fantrax's error envelope — **returned under
      HTTP 200** — becomes ``SourceRejected``;
    * a body that is JSON of the wrong shape becomes ``SourceContractError``
      from the parser.
"""

from __future__ import annotations

import contextlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from typing import Any, Final

from hoops_gm.ingest.errors import (
    CredentialsExpired,
    SourceContractError,
    SourceRejected,
    SourceUnavailable,
)
from hoops_gm.ingest.fantrax_official.models import (
    FantraxAdpEntry,
    FantraxDraftPick,
    FantraxLeagueInfo,
    FantraxPlayerIds,
)
from hoops_gm.ingest.fantrax_official.parsers import (
    SOURCE,
    parse_adp,
    parse_draft_picks,
    parse_league_info,
    parse_player_ids,
)
from hoops_gm.ingest.rawstore import RawPayloadStore
from hoops_gm.ingest.retry import RetryPolicy, call_with_retry
from hoops_gm.ingest.throttle import RateLimiter

BASE_URL: Final = "https://www.fantrax.com/fxea/general"

#: One request every two seconds. See the module docstring.
DEFAULT_MIN_INTERVAL_SECONDS: Final = 2.0
DEFAULT_TIMEOUT_SECONDS: Final = 30.0

#: A player-id map and an ADP list are daily-cadence data at best, so a cached
#: capture from the last six hours is used in preference to another request.
DEFAULT_MAX_AGE: Final = timedelta(hours=6)

#: Status codes that mean "come back later" rather than "you are wrong".
_RETRYABLE_STATUS: Final = frozenset({408, 425, 429, 500, 502, 503, 504})

#: Fantrax refuses the default ``urllib`` User-Agent with **HTTP 403**, while
#: answering the identical URL for a browser-shaped one — found by recording
#: the fixtures, after the same endpoints had answered PowerShell's
#: ``Invoke-WebRequest`` all afternoon. It is not authentication and not rate
#: limiting; it is a user-agent filter, and without these headers every
#: endpoint on this source is unreachable.
#:
#: The User-Agent is honest about what this is rather than impersonating
#: Chrome: it names the project and stays identifiable in Fantrax's logs, which
#: matters for a read-only client against a beta endpoint.
DEFAULT_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "hoops-gm/0.1 (personal fantasy basketball tool; "
        "+https://github.com/SR2501/hoops-gm) python-urllib"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


class FantraxOfficialClient:
    """Reads the Fantrax official endpoints, capturing every raw response.

    The store is optional so a caller can use the client without a filesystem,
    but the normal path always captures: a payload that is not kept cannot be
    replayed when the number it produced turns out to be wrong.
    """

    def __init__(
        self,
        *,
        store: RawPayloadStore | None = None,
        base_url: str = BASE_URL,
        limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        user_secret_id: str | None = None,
        headers: dict[str, str] | None = None,
        opener: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.store = store
        self.limiter = limiter or RateLimiter(DEFAULT_MIN_INTERVAL_SECONDS)
        self.retry_policy = retry_policy or RetryPolicy()
        self.timeout_seconds = timeout_seconds
        self.user_secret_id = user_secret_id
        self.headers = dict(DEFAULT_HEADERS if headers is None else headers)
        # Injectable so a test can drive the transport without a network, and
        # without monkeypatching a module global.
        self._opener = opener or urllib.request.urlopen

    # -- endpoints ---------------------------------------------------------

    def get_player_ids(
        self, *, sport: str = "NBA", max_age: timedelta | None = None
    ) -> FantraxPlayerIds:
        payload = self.fetch_json("getPlayerIds", {"sport": sport}, max_age=max_age)
        return parse_player_ids(payload)

    def get_adp(
        self, *, sport: str = "NBA", limit: int | None = None, max_age: timedelta | None = None
    ) -> list[FantraxAdpEntry]:
        """Fetch ADP.

        ``limit`` is passed through unchanged and **is not corrected**. The
        endpoint returns ``limit - 1`` rows: verified for 1, 2, 3, 5 and 10 on
        2026-08-17, where ``limit=1`` returns zero rows. Quietly adding one
        would hide an upstream fix and make our behaviour depend on when the
        caller read this docstring. The behaviour is pinned by a contract test
        instead; callers who want N rows should ask for ``N + 1`` knowingly, or
        omit the parameter, which returns everything.
        """
        params: dict[str, Any] = {"sport": sport}
        if limit is not None:
            params["limit"] = limit
        payload = self.fetch_json("getAdp", params, max_age=max_age)
        return parse_adp(payload)

    def get_league_info(
        self, league_id: str, *, max_age: timedelta | None = None
    ) -> FantraxLeagueInfo:
        payload = self.fetch_json("getLeagueInfo", self._league_params(league_id), max_age=max_age)
        return parse_league_info(payload, league_id=league_id)

    def get_draft_picks(
        self, league_id: str, *, max_age: timedelta | None = None
    ) -> list[FantraxDraftPick]:
        payload = self.fetch_json("getDraftPicks", self._league_params(league_id), max_age=max_age)
        return parse_draft_picks(payload)

    # -- transport ---------------------------------------------------------

    def fetch_json(
        self,
        endpoint: str,
        params: dict[str, Any],
        *,
        max_age: timedelta | None = None,
    ) -> Any:
        """Fetch and decode, preferring a recent capture over a live request."""
        window = DEFAULT_MAX_AGE if max_age is None else max_age

        if self.store is not None:
            cached = self.store.fresh(
                source=SOURCE, endpoint=endpoint, params=params, max_age=window
            )
            if cached is not None:
                return self._decode(cached.read_bytes(), endpoint=endpoint)

        body, status, content_type = call_with_retry(
            lambda: self._request(endpoint, params),
            policy=self.retry_policy,
        )

        if self.store is not None:
            # Captured before decoding: a body that fails to parse is exactly
            # the body worth still having afterwards.
            self.store.put(
                source=SOURCE,
                endpoint=endpoint,
                params=params,
                body=body,
                http_status=status,
                content_type=content_type,
            )

        return self._decode(body, endpoint=endpoint)

    def _league_params(self, league_id: str) -> dict[str, Any]:
        params: dict[str, Any] = {"leagueId": league_id}
        if self.user_secret_id:
            params["userSecretId"] = self.user_secret_id
        return params

    def _request(self, endpoint: str, params: dict[str, Any]) -> tuple[bytes, int, str | None]:
        url = f"{self.base_url}/{endpoint}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers=dict(self.headers))
        self.limiter.acquire()
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                return (
                    response.read(),
                    getattr(response, "status", 200),
                    response.headers.get("Content-Type"),
                )
        except urllib.error.HTTPError as exc:
            body = _read_error_body(exc)
            if exc.code in _RETRYABLE_STATUS:
                raise SourceUnavailable(
                    f"HTTP {exc.code}", source=SOURCE, endpoint=endpoint, detail=body[:400]
                ) from exc
            if exc.code in {401, 407}:
                raise CredentialsExpired(
                    f"HTTP {exc.code}: authentication rejected",
                    source=SOURCE,
                    endpoint=endpoint,
                    detail=body[:400],
                ) from exc
            # Every other 4xx is the source answering coherently and refusing.
            # That is a rejection, not a contract error: the shape of the
            # response tells us nothing about whether the parser still works,
            # and conflating the two makes a mistyped league id look like
            # upstream drift.
            raise SourceRejected(
                f"HTTP {exc.code}", source=SOURCE, endpoint=endpoint, detail=body[:400]
            ) from exc
        except urllib.error.URLError as exc:
            raise SourceUnavailable(
                f"could not reach the source: {exc.reason}", source=SOURCE, endpoint=endpoint
            ) from exc
        except TimeoutError as exc:
            raise SourceUnavailable(
                f"timed out after {self.timeout_seconds}s", source=SOURCE, endpoint=endpoint
            ) from exc
        except OSError as exc:
            raise SourceUnavailable(
                f"transport failure: {exc}", source=SOURCE, endpoint=endpoint
            ) from exc

    @staticmethod
    def _decode(body: bytes, *, endpoint: str) -> Any:
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceContractError(
                f"response was not JSON: {exc}",
                source=SOURCE,
                endpoint=endpoint,
                detail=body[:200],
            ) from exc


def _read_error_body(exc: urllib.error.HTTPError) -> bytes:
    """Read an error response body without letting that reading fail the call.

    ``HTTPError.fp`` may be ``None``, and reading a partially consumed error
    stream can raise. The body is diagnostic detail attached to an exception we
    are already raising — losing it must not replace a clear "HTTP 403" with an
    obscure secondary error.
    """
    try:
        return exc.read()
    except Exception:  # diagnostic only; see the docstring
        return b""
    finally:
        with contextlib.suppress(Exception):
            exc.close()
