"""Failure modes of an external source, separated by what should happen next.

The distinction is not cosmetic. It decides whether the caller retries, and
retrying the wrong class of failure is actively harmful: hammering
``stats.nba.com`` for a payload whose schema has changed will never succeed and
will get us throttled, while treating a transient timeout as permanent throws
away a backfill.

Three classes, and the boundary between the first two is the one that matters:

``SourceUnavailable``
    The source could not be reached, or answered with something that says
    "try again" — a timeout, a reset connection, a 5xx. **Retryable.**

``SourceRejected``
    The source was reached and answered coherently, but refused the request:
    a missing parameter, a bad league id, an expired session. **Not
    retryable** — the request is wrong, and repeating it is rude.

    This is not a theoretical category. ``fantrax.com/fxea/general/getLeagueInfo``
    with no ``leagueId`` returns **HTTP 200** with
    ``{"error": {"code": "WARNING", "message": "Missing 'leagueId' parameter"}}``
    (verified 2026-08-17). Any client that trusts the status code treats that
    as success and hands an error envelope to a parser as though it were data.

``SourceContractError``
    The source answered, and the answer does not have the shape we recorded.
    **Not retryable, and the loudest of the three** — this is upstream drift,
    which is precisely the silent-wrong-number failure the Adapter gate exists
    to convert into a red build (ADR-006).

:class:`CredentialsExpired` refines ``SourceRejected`` because "your Fantrax
cookie expired" has a specific documented remedy and a generic refusal does not.
"""

from __future__ import annotations

from typing import Any


class SourceError(Exception):
    """Base for every external-source failure.

    ``source`` and ``endpoint`` are attributes rather than only text in the
    message, so a handler can branch on them and a log line can index them.
    """

    #: Whether repeating the identical request could plausibly succeed.
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        source: str,
        endpoint: str | None = None,
        detail: Any = None,
    ) -> None:
        self.source = source
        self.endpoint = endpoint
        self.detail = detail
        location = f"{source}.{endpoint}" if endpoint else source
        super().__init__(f"[{location}] {message}")


class SourceUnavailable(SourceError):
    """Could not reach the source, or it asked us to come back later."""

    retryable = True


class SourceRejected(SourceError):
    """The source answered and refused the request.

    Covers an application-level error envelope returned under HTTP 200, which
    Fantrax does, as well as an honest 4xx.
    """

    retryable = False


class CredentialsExpired(SourceRejected):
    """Authentication is stale and a human has to refresh it.

    Raised in preference to a bare :class:`SourceRejected` because the remedy
    is specific and documented — see ``docs/adapters/fantrax-private.md``.
    """


class SourceContractError(SourceError):
    """The payload does not match the recorded shape.

    Never swallowed and never retried. A parser raising this means either the
    upstream changed or our recorded fixture is stale, and both need a person.

    Regenerating the fixture to make the resulting test pass defeats the whole
    mechanism — see ADR-006.
    """

    retryable = False
