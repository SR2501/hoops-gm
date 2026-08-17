"""Request pacing.

``stats.nba.com`` is documented as tolerating roughly one request per second
and is known to stop answering when pushed harder. A multi-season backfill is
thousands of requests, so pacing is not a nicety — it is the difference between
a backfill that finishes and an address that stops getting answers.

The limiter is deliberately trivial and deliberately injectable. ``monotonic``
and ``sleep`` are parameters so a test can assert the pacing arithmetic without
spending real seconds; a limiter that can only be tested by waiting is a
limiter nobody tests.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    """Enforce a minimum interval between successive calls to :meth:`acquire`.

    Thread-safe, because a backfill that later grows a worker pool should not
    quietly stop being paced.
    """

    #: Seconds that must elapse between two acquisitions.
    min_interval_seconds: float
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    _last_acquired: float | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must not be negative")

    def acquire(self) -> float:
        """Block until the next request is allowed. Returns seconds waited."""
        with self._lock:
            now = self.monotonic()
            if self._last_acquired is None:
                self._last_acquired = now
                return 0.0

            earliest = self._last_acquired + self.min_interval_seconds
            wait = earliest - now
            if wait > 0:
                self.sleep(wait)
                # Advance from the scheduled slot, not from "now". Using the
                # post-sleep clock lets the interval creep upward by the cost
                # of each call, which over thousands of requests turns a
                # 20-minute backfill into a much longer one.
                self._last_acquired = earliest
                return wait

            self._last_acquired = now
            return 0.0

    def reset(self) -> None:
        """Forget the last acquisition, so the next one does not wait."""
        with self._lock:
            self._last_acquired = None
