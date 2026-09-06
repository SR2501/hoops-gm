"""Operator command for the draft-day preseason news snapshot."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hoops_gm.core.config import get_settings
from hoops_gm.db.session import Database, absent_store_refusal
from hoops_gm.ingest.preseason_news.client import PreseasonNewsClient
from hoops_gm.ingest.preseason_news.freshness import MAX_NEWS_AGE, assess_news_freshness
from hoops_gm.ingest.preseason_news.report import write_preseason_news_report
from hoops_gm.ingest.preseason_news.resolver import resolve_preseason_news
from hoops_gm.ingest.rawstore import RawPayloadStore

DEFAULT_RAW_ROOT = Path("data") / "raw"
DEFAULT_REPORT_PATH = Path("data") / "reports" / "preseason_news.json"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def main(
    argv: Sequence[str] | None = None,
    *,
    now: Callable[[], datetime] = _utc_now,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument(
        "--max-news-age-hours",
        type=float,
        default=MAX_NEWS_AGE.total_seconds() / 3600,
        help="maximum age of the newest item before exit 3 (default: 336)",
    )
    args = parser.parse_args(argv)
    if args.max_news_age_hours <= 0:
        parser.error("--max-news-age-hours must be positive")

    settings = get_settings()
    if (refusal := absent_store_refusal(settings.database_url)) is not None:
        parser.error(refusal)

    snapshot = PreseasonNewsClient(store=RawPayloadStore(DEFAULT_RAW_ROOT)).latest()
    database = Database.from_settings(settings)
    try:
        with database.session() as session:
            resolution = resolve_preseason_news(session, snapshot.feed.items)
    finally:
        database.dispose()

    freshness = assess_news_freshness(
        snapshot,
        max_age=timedelta(hours=args.max_news_age_hours),
        assessed_at=now(),
    )
    write_preseason_news_report(
        args.output,
        snapshot=snapshot,
        resolution=resolution,
        freshness=freshness,
    )
    print(f"preseason news: {len(resolution.resolved)} resolved")
    print(f"unresolved     : {len(resolution.unresolved)}")
    print(f"freshness      : {'fresh' if freshness.is_fresh else 'STALE'}")
    print(f"report         : {args.output}")
    if not freshness.is_fresh:
        print(f"diagnostic     : {freshness.diagnostic}")
        return 3
    return 0 if not resolution.unresolved else 2
