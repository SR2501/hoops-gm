"""Freshness policy for operator-visible preseason news snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from hoops_gm.ingest.preseason_news.models import PreseasonNewsSnapshot

MAX_NEWS_AGE: Final = timedelta(days=14)


@dataclass(frozen=True)
class NewsFreshness:
    """Whether the newest item is recent enough to use as current evidence."""

    is_fresh: bool
    assessed_at: datetime
    age: timedelta
    max_age: timedelta
    diagnostic: str | None


def assess_news_freshness(
    snapshot: PreseasonNewsSnapshot,
    *,
    max_age: timedelta = MAX_NEWS_AGE,
    assessed_at: datetime | None = None,
) -> NewsFreshness:
    """Assess freshness when evidence is used, independent of its capture time."""
    if max_age <= timedelta(0):
        raise ValueError("max_age must be positive")
    assessed_at = assessed_at or datetime.now(UTC)
    if assessed_at.tzinfo is None:
        raise ValueError("assessed_at must be timezone-aware")
    assessed_at = assessed_at.astimezone(UTC)
    newest = snapshot.feed.items[0]
    age = assessed_at - newest.published_at
    is_fresh = age <= max_age
    diagnostic = None
    if not is_fresh:
        diagnostic = (
            f"newest item {newest.guid} was published at "
            f"{newest.published_at.isoformat()}, {age.total_seconds():.0f} seconds "
            f"before the freshness assessment; limit is "
            f"{max_age.total_seconds():.0f} seconds"
        )
    return NewsFreshness(
        is_fresh=is_fresh,
        assessed_at=assessed_at,
        age=age,
        max_age=max_age,
        diagnostic=diagnostic,
    )
