"""Transport for ``stats.nba.com``, via ``nba_api`` and only via ``nba_api``.

**Do not replace this with a hand-rolled HTTP client.** Verified 2026-08-17
(risk R27): ``curl`` against ``stats.nba.com`` with the complete documented
header set — User-Agent, Referer, Origin, ``x-nba-stats-origin``,
``x-nba-stats-token`` — is met with a connection reset after about 21 seconds,
while ``nba_api`` 1.11.4 reaches the same host and returns data. A ``curl``
failure against this host is not evidence the host is down.

Documented behaviour:

Throttling
    One request per 1.1 seconds. The commonly cited limit is ~1 req/s and this
    sits just under it, because a multi-season backfill is thousands of
    requests and the cost of being throttled mid-backfill is far higher than
    the cost of the extra 100ms.

Retry
    Three attempts, exponential backoff, only on :class:`SourceUnavailable`.

Caching
    Every response is captured, and a capture younger than ``max_age`` is used
    instead of a request. Completed games never change, so the default window
    for a per-game endpoint is effectively forever — which is what makes a
    2,460-request season backfill resumable after a crash instead of restarted.

When the source is down
    ``nba_api`` raises ``requests`` exceptions, which become
    ``SourceUnavailable`` and are retried.

When the source returns garbage
    ``nba_api`` does **not** fail cleanly on a bad request. A nonexistent game
    id produces ``AttributeError: 'NoneType' object has no attribute 'get'``
    from inside the library, not an exception describing the problem — verified
    2026-08-17. Every call is therefore wrapped, and any non-``SourceError``
    exception escaping the library becomes a :class:`SourceContractError`
    naming the endpoint, so an unparseable response is attributed to the source
    rather than surfacing as an unexplained ``AttributeError`` in a backfill
    log.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any, Final

from hoops_gm.ingest.errors import SourceContractError, SourceError, SourceUnavailable
from hoops_gm.ingest.nba.parsers import SOURCE
from hoops_gm.ingest.rawstore import RawPayloadStore
from hoops_gm.ingest.retry import RetryPolicy, call_with_retry
from hoops_gm.ingest.throttle import RateLimiter

#: Just under the commonly cited one-request-per-second limit.
DEFAULT_MIN_INTERVAL_SECONDS: Final = 1.1
DEFAULT_TIMEOUT_SECONDS: Final = 60.0

#: A finished game's box score is immutable, so a capture of one never needs
#: refreshing. Ten years is "forever" expressed as a number the cache can use.
COMPLETED_GAME_MAX_AGE: Final = timedelta(days=3650)
#: Player and schedule listings do change — a trade moves a player, a game is
#: postponed — so they get a real window.
ROSTER_MAX_AGE: Final = timedelta(hours=12)
SEASON_MAX_AGE: Final = timedelta(hours=12)


class NbaStatsClient:
    """Throttled, cached, capture-everything access to ``stats.nba.com``.

    ``endpoint_factory`` exists so tests can drive the transport without a
    network. It takes an endpoint name and keyword arguments and returns
    something with a ``get_dict()``; in production it is
    :func:`_default_endpoint_factory`, which dispatches into ``nba_api``.
    """

    def __init__(
        self,
        *,
        store: RawPayloadStore | None = None,
        limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        endpoint_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.store = store
        self.limiter = limiter or RateLimiter(DEFAULT_MIN_INTERVAL_SECONDS)
        self.retry_policy = retry_policy or RetryPolicy()
        self.timeout_seconds = timeout_seconds
        self._endpoint_factory = endpoint_factory or _default_endpoint_factory

    # -- endpoints ---------------------------------------------------------

    def static_teams(self) -> Any:
        """The packaged team list. No network, so no throttle and no capture."""
        from nba_api.stats.static import teams as static_teams

        return static_teams.get_teams()

    def common_all_players(
        self, *, season: str, only_current: bool = False, max_age: timedelta | None = None
    ) -> Any:
        return self.fetch(
            "CommonAllPlayers",
            {
                "season": season,
                "is_only_current_season": 1 if only_current else 0,
                # ``league_id``, not ``league_id_nullable``. The three endpoints
                # this client uses spell the same parameter three different
                # ways, which is why every call site is pinned by a live smoke
                # test rather than trusted.
                "league_id": "00",
            },
            max_age=ROSTER_MAX_AGE if max_age is None else max_age,
        )

    def league_game_finder(
        self,
        *,
        season: str,
        season_type: str = "Regular Season",
        max_age: timedelta | None = None,
    ) -> Any:
        return self.fetch(
            "LeagueGameFinder",
            {
                "season_nullable": season,
                "season_type_nullable": season_type,
                "league_id_nullable": "00",
            },
            max_age=SEASON_MAX_AGE if max_age is None else max_age,
        )

    def player_game_logs(
        self,
        *,
        season: str,
        season_type: str = "Regular Season",
        max_age: timedelta | None = None,
    ) -> Any:
        return self.fetch(
            "PlayerGameLogs",
            {"season_nullable": season, "season_type_nullable": season_type},
            max_age=SEASON_MAX_AGE if max_age is None else max_age,
        )

    def box_score_traditional(self, game_id: str, *, max_age: timedelta | None = None) -> Any:
        return self.fetch(
            "BoxScoreTraditionalV3",
            {"game_id": game_id},
            max_age=COMPLETED_GAME_MAX_AGE if max_age is None else max_age,
        )

    def box_score_summary(self, game_id: str, *, max_age: timedelta | None = None) -> Any:
        """Fetch the game summary.

        V3 only. ``BoxScoreSummaryV2`` is deliberately not exposed by this
        client at all: its ``InactivePlayers`` table silently returned zero
        rows for every 2025-26 date after opening night, and an endpoint that
        answers "nobody was inactive" when it means "I no longer know" is worse
        than one that fails.
        """
        return self.fetch(
            "BoxScoreSummaryV3",
            {"game_id": game_id},
            max_age=COMPLETED_GAME_MAX_AGE if max_age is None else max_age,
        )

    # -- transport ---------------------------------------------------------

    def fetch(
        self, endpoint: str, params: dict[str, Any], *, max_age: timedelta = SEASON_MAX_AGE
    ) -> Any:
        """Call an endpoint, preferring a recent capture over a request."""
        if self.store is not None:
            cached = self.store.fresh(
                source=SOURCE, endpoint=endpoint, params=params, max_age=max_age
            )
            if cached is not None:
                return cached.read_json()

        payload = call_with_retry(lambda: self._invoke(endpoint, params), policy=self.retry_policy)

        if self.store is not None:
            self.store.put(
                source=SOURCE,
                endpoint=endpoint,
                params=params,
                body=json.dumps(payload).encode("utf-8"),
                content_type="application/json",
            )
        return payload

    def _invoke(self, endpoint: str, params: dict[str, Any]) -> Any:
        self.limiter.acquire()
        try:
            instance = self._endpoint_factory(endpoint, timeout=self.timeout_seconds, **params)
            return instance.get_dict()
        except SourceError:
            raise
        except Exception as exc:
            # nba_api leaks whatever went wrong at whatever layer it went
            # wrong: requests' Timeout and ConnectionError for transport, and a
            # bare AttributeError from its own parsing when the response is not
            # the shape it expected. Classified here so a backfill log says
            # which endpoint failed and whether retrying could help, instead of
            # showing a NoneType AttributeError with no context.
            if _is_transport_failure(exc):
                raise SourceUnavailable(
                    f"{type(exc).__name__}: {exc}", source=SOURCE, endpoint=endpoint
                ) from exc
            raise SourceContractError(
                f"nba_api failed to parse the response ({type(exc).__name__}: {exc}); "
                "the endpoint may have changed or the request may name something "
                "that does not exist",
                source=SOURCE,
                endpoint=endpoint,
                detail=params,
            ) from exc


#: Exception type names that mean transport rather than schema. Matched by name
#: so this module does not import ``requests`` merely to classify an error.
_TRANSPORT_EXCEPTION_NAMES: Final = frozenset(
    {
        "ConnectionError",
        "ConnectTimeout",
        "ChunkedEncodingError",
        "HTTPError",
        "ProxyError",
        "ReadTimeout",
        "RemoteDisconnected",
        "RequestException",
        "SSLError",
        "Timeout",
        "TimeoutError",
        "TooManyRedirects",
        "URLError",
    }
)


def _is_transport_failure(exc: BaseException) -> bool:
    return any(
        klass.__name__ in _TRANSPORT_EXCEPTION_NAMES for klass in type(exc).__mro__
    ) or isinstance(exc, OSError)


def _default_endpoint_factory(endpoint: str, **kwargs: Any) -> Any:
    """Dispatch an endpoint name into ``nba_api``.

    Imported lazily so that importing :mod:`hoops_gm` does not pull in
    ``nba_api`` and, transitively, pandas and numpy. The API process has no use
    for any of them.
    """
    from nba_api.stats.endpoints import (
        boxscoresummaryv3,
        boxscoretraditionalv3,
        commonallplayers,
        leaguegamefinder,
        playergamelogs,
    )

    factories: dict[str, Callable[..., Any]] = {
        "CommonAllPlayers": commonallplayers.CommonAllPlayers,
        "LeagueGameFinder": leaguegamefinder.LeagueGameFinder,
        "PlayerGameLogs": playergamelogs.PlayerGameLogs,
        "BoxScoreTraditionalV3": boxscoretraditionalv3.BoxScoreTraditionalV3,
        "BoxScoreSummaryV3": boxscoresummaryv3.BoxScoreSummaryV3,
    }
    factory = factories.get(endpoint)
    if factory is None:
        raise SourceContractError(
            f"no factory registered for endpoint {endpoint!r}", source=SOURCE, endpoint=endpoint
        )
    return factory(**kwargs)
