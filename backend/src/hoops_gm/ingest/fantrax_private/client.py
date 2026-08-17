"""Private-league reads via ``fantraxapi``.

``fantraxapi`` wraps ``/fxpa/req``, the internal JSON-RPC the Fantrax SPA uses.
It is undocumented, read-only from our side, and requires a ``FANTRAXUSER``
session cookie. **The version is pinned exactly** in ``pyproject.toml``: an
internal endpoint can change shape without notice, and a floating dependency
means that change arrives as a silent behaviour difference rather than as a
deliberate upgrade.

Pinned at ``fantraxapi==1.0.1``. Note that the plan's suggested ``0.3.0`` does
not exist on PyPI — the published versions jump from ``0.2.9`` to ``1.0.0``,
and 1.0.x has a different API surface from the 0.2.x line most examples online
use.

## What this adapter does and does not claim

It owns **transport and error translation**: holding the session, spending the
cookie, and converting ``fantraxapi``'s exceptions into this project's
vocabulary so a caller can tell "log in again" from "Fantrax is down" from
"the payload changed".

It deliberately does **not** ship parsers for the roster, standings and matchup
payloads. No real payload has ever been seen — that needs a league id and a
live session cookie, and neither existed when this was written. Writing parsers
against a guessed shape would produce exactly what ADR-006 rejects: hand-written
mocks encoding what we assume rather than what the source returns, with a
contract test that proves only that our assumption is self-consistent.

So the typed objects ``fantraxapi`` already returns are passed through, and the
first person with a live cookie should capture real payloads with
:meth:`FantraxPrivateClient.capture`, commit them as fixtures, and write the
parsers against those. That is recorded in ``docs/handoff.md`` as unfinished
rather than presented as done.

## Documented behaviour

Throttling
    One request every two seconds. This is somebody's live account against
    undocumented internal infrastructure; there is no reason to be quick.

Retry
    Two attempts, only on :class:`SourceUnavailable`. Lower than elsewhere
    because a failing authenticated request against internal infrastructure is
    more likely to be a session problem than a blip, and repeating it is how a
    session gets flagged.

When the source is down
    Transport failures become ``SourceUnavailable`` and are retried once.

When authentication fails
    ``NotLoggedIn`` becomes :class:`CredentialsExpired`, which names the
    documented recovery procedure. This is the expected steady-state failure —
    session cookies expire — so it is a distinct class rather than a generic
    refusal.

When the source returns garbage
    Anything else from the library becomes :class:`SourceContractError`, which
    is never retried and is meant to be loud.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from hoops_gm.ingest.errors import (
    CredentialsExpired,
    SourceContractError,
    SourceError,
    SourceUnavailable,
)
from hoops_gm.ingest.fantrax_private.cookies import SOURCE, CookieStore
from hoops_gm.ingest.rawstore import RawPayloadStore
from hoops_gm.ingest.retry import RetryPolicy, call_with_retry
from hoops_gm.ingest.throttle import RateLimiter

DEFAULT_MIN_INTERVAL_SECONDS: Final = 2.0
COOKIE_NAME: Final = "FANTRAXUSER"

#: ``fantraxapi`` exception names that mean the session is stale.
_AUTH_EXCEPTION_NAMES: Final = frozenset({"NotLoggedIn", "NotMemberOfLeague"})

_TRANSPORT_EXCEPTION_NAMES: Final = frozenset(
    {
        "ConnectionError",
        "ConnectTimeout",
        "ChunkedEncodingError",
        "ProxyError",
        "ReadTimeout",
        "RemoteDisconnected",
        "SSLError",
        "Timeout",
        "TimeoutError",
    }
)

RELOGIN_INSTRUCTIONS: Final = (
    "The Fantrax session cookie is stale. Capture a fresh FANTRAXUSER cookie by "
    "following docs/adapters/fantrax-private.md, then run:\n"
    "    python -m hoops_gm.ingest.fantrax_private.cookies --store"
)


def build_session(cookie: str) -> Any:
    """A ``requests`` session carrying the Fantrax cookie.

    Kept separate from the client so a caller can inspect exactly what is being
    sent, and so the cookie's journey from the encrypted store into a header is
    one readable function rather than a constructor side effect.
    """
    import requests

    session = requests.Session()
    session.cookies.set(COOKIE_NAME, cookie, domain=".fantrax.com")
    session.headers.update(
        {
            "User-Agent": (
                "hoops-gm/0.1 (personal fantasy basketball tool; "
                "+https://github.com/SR2501/hoops-gm)"
            )
        }
    )
    return session


class FantraxPrivateClient:
    """Read-only access to a private Fantrax league.

    ``league_factory`` is injectable so the error translation — which is the
    only logic here — can be tested without a cookie, a league or a network.
    """

    def __init__(
        self,
        league_id: str,
        *,
        cookie_store: CookieStore | None = None,
        store: RawPayloadStore | None = None,
        limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        league_factory: Callable[[str, Any], Any] | None = None,
    ) -> None:
        if not league_id:
            raise ValueError("league_id is required")
        self.league_id = league_id
        self.cookie_store = cookie_store
        self.store = store
        self.limiter = limiter or RateLimiter(DEFAULT_MIN_INTERVAL_SECONDS)
        self.retry_policy = retry_policy or RetryPolicy(attempts=2)
        self._league_factory = league_factory or _default_league_factory
        self._league: Any | None = None

    # -- session -----------------------------------------------------------

    @property
    def league(self) -> Any:
        """The ``fantraxapi`` league, built on first use."""
        if self._league is None:
            store = self.cookie_store or CookieStore.from_environment()
            self._league = self._league_factory(self.league_id, build_session(store.read()))
        return self._league

    def reset_session(self) -> None:
        """Forget the current session so the next call re-reads the cookie.

        Called after a human has stored a fresh cookie, so a long-running
        process picks it up without a restart.
        """
        self._league = None

    # -- reads -------------------------------------------------------------

    def standings(self, **kwargs: Any) -> Any:
        return self._call("standings", lambda league: league.standings(**kwargs))

    def team_roster(self, team_id: str, **kwargs: Any) -> Any:
        return self._call("team_roster", lambda league: league.team_roster(team_id, **kwargs))

    def scoring_period_results(self, period: int, **kwargs: Any) -> Any:
        return self._call(
            "scoring_period_results", lambda league: league.scoring_period_results(period, **kwargs)
        )

    def transactions(self, **kwargs: Any) -> Any:
        return self._call("transactions", lambda league: league.transactions(**kwargs))

    def teams(self) -> Any:
        return self._call("team_lookup", lambda league: league.team_lookup)

    # -- capture -----------------------------------------------------------

    def capture(self, endpoint: str, method: str, **kwargs: Any) -> Any:
        """Call an arbitrary ``fantraxapi`` method and keep the raw result.

        The tool for the person who first has a live cookie: it records what
        the private endpoints actually return so that fixtures and contract
        tests can be written against reality instead of against a guess.
        """
        result = self._call(endpoint, lambda league: getattr(league, method)(**kwargs))
        if self.store is not None:
            import json

            self.store.put(
                source=SOURCE,
                endpoint=endpoint,
                params={"league_id": self.league_id, "method": method, **kwargs},
                body=json.dumps(result, default=repr).encode("utf-8"),
                content_type="application/json",
            )
        return result

    # -- internals ---------------------------------------------------------

    def _call(self, endpoint: str, operation: Callable[[Any], Any]) -> Any:
        def invoke() -> Any:
            self.limiter.acquire()
            try:
                return operation(self.league)
            except SourceError:
                raise
            except Exception as exc:
                raise _translate(exc, endpoint=endpoint) from exc

        return call_with_retry(invoke, policy=self.retry_policy)


def _translate(exc: BaseException, *, endpoint: str) -> SourceError:
    """Turn a ``fantraxapi`` exception into this project's vocabulary."""
    names = {klass.__name__ for klass in type(exc).__mro__}

    if names & _AUTH_EXCEPTION_NAMES:
        return CredentialsExpired(
            f"{type(exc).__name__}: {exc}\n\n{RELOGIN_INSTRUCTIONS}",
            source=SOURCE,
            endpoint=endpoint,
        )
    if names & _TRANSPORT_EXCEPTION_NAMES or isinstance(exc, OSError):
        return SourceUnavailable(f"{type(exc).__name__}: {exc}", source=SOURCE, endpoint=endpoint)
    return SourceContractError(
        f"{type(exc).__name__}: {exc}; /fxpa/req is undocumented internal "
        "infrastructure and may have changed shape",
        source=SOURCE,
        endpoint=endpoint,
    )


def _default_league_factory(league_id: str, session: Any) -> Any:
    from fantraxapi import League

    return League(league_id, session=session)


def cookie_store_for(path: Path | None = None) -> CookieStore:
    return CookieStore.from_environment(path=path)
