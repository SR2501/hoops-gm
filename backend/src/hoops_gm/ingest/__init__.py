"""Ingestion: every path by which external data enters the system.

Each source sits behind an adapter that separates three concerns which fail in
different ways and must therefore be tested differently:

* **transport** — throttling, retry, caching, raw capture;
* **parsing** — pure functions from a decoded payload to typed records, which
  is what the recorded-fixture contract tests exercise;
* **import** — writing parsed records into the database.

Keeping parsing pure is what makes the Adapter gate cheap: a contract test
loads a committed fixture, calls the parser and asserts, with no network and no
database. See ADR-006 and ``docs/governance/gates.md``.
"""

from hoops_gm.ingest.errors import (
    CredentialsExpired,
    SourceContractError,
    SourceError,
    SourceRejected,
    SourceUnavailable,
)
from hoops_gm.ingest.rawstore import RawPayloadRef, RawPayloadStore
from hoops_gm.ingest.retry import RetryPolicy, call_with_retry
from hoops_gm.ingest.throttle import RateLimiter

__all__ = [
    "CredentialsExpired",
    "RateLimiter",
    "RawPayloadRef",
    "RawPayloadStore",
    "RetryPolicy",
    "SourceContractError",
    "SourceError",
    "SourceRejected",
    "SourceUnavailable",
    "call_with_retry",
]
