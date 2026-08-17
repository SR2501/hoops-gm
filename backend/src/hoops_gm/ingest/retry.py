"""Retry with exponential backoff, for the one failure class that deserves it.

**Only :class:`~hoops_gm.ingest.errors.SourceUnavailable` is retried.** A
refused request and a changed schema will both fail identically on the second
attempt, and retrying them wastes the request budget of a source we are
supposed to be gentle with. Worse, a retry loop around a contract error delays
the loud failure that ADR-006 exists to produce.

Jitter is proportional rather than absolute so that a backfill which trips a
rate limit does not resynchronise every retry onto the same instant.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from hoops_gm.ingest.errors import SourceError


@dataclass(frozen=True)
class RetryPolicy:
    """How many times to retry a retryable failure, and how long to wait."""

    #: Total attempts including the first. ``1`` disables retrying.
    attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    multiplier: float = 2.0
    #: Fraction of the computed delay to randomise by, in ``[0, 1]``.
    jitter: float = 0.25

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts must be at least 1")
        if not 0.0 <= self.jitter <= 1.0:
            raise ValueError("jitter must be in [0, 1]")

    def delay_for(self, attempt: int, *, rand: Callable[[], float] = random.random) -> float:
        """Delay before ``attempt`` (1-based, so attempt 2 is the first retry)."""
        raw = self.base_delay_seconds * (self.multiplier ** max(0, attempt - 2))
        capped = min(raw, self.max_delay_seconds)
        if self.jitter == 0.0:
            return capped
        # Symmetric around the capped delay, floored at zero.
        offset = capped * self.jitter * (2.0 * rand() - 1.0)
        return max(0.0, capped + offset)


def call_with_retry[T](
    operation: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    on_retry: Callable[[int, SourceError, float], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
) -> T:
    """Call ``operation``, retrying only retryable :class:`SourceError`s.

    Non-``SourceError`` exceptions propagate untouched: an adapter is expected
    to have already translated whatever its library threw into the vocabulary
    in :mod:`hoops_gm.ingest.errors`. Anything that has not been translated is
    a bug in the adapter, and hiding it behind a retry loop makes it harder to
    find, not easier.
    """
    policy = policy or RetryPolicy()
    last: SourceError | None = None

    for attempt in range(1, policy.attempts + 1):
        try:
            return operation()
        except SourceError as exc:
            if not exc.retryable or attempt == policy.attempts:
                raise
            last = exc
            delay = policy.delay_for(attempt + 1, rand=rand)
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            sleep(delay)

    # Unreachable: the loop either returns or raises. Present so the function
    # is total rather than relying on the reader to prove that.
    raise last if last is not None else RuntimeError("retry loop exited without a result")
