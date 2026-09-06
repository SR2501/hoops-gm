"""Preseason NBA player-news ingestion."""

from hoops_gm.ingest.preseason_news.client import (
    DEFAULT_MAX_AGE,
    DEFAULT_MIN_INTERVAL_SECONDS,
    PreseasonNewsClient,
)
from hoops_gm.ingest.preseason_news.models import (
    PreseasonNewsFeed,
    PreseasonNewsItem,
    PreseasonNewsResolution,
    PreseasonNewsSnapshot,
    ResolvedPreseasonNewsItem,
    UnresolvedPreseasonNewsItem,
)
from hoops_gm.ingest.preseason_news.parser import (
    ENDPOINT,
    MAX_BODY_BYTES,
    RSS_URL,
    SOURCE,
    parse_preseason_news,
)
from hoops_gm.ingest.preseason_news.report import write_preseason_news_report
from hoops_gm.ingest.preseason_news.resolver import resolve_preseason_news

__all__ = [
    "DEFAULT_MAX_AGE",
    "DEFAULT_MIN_INTERVAL_SECONDS",
    "ENDPOINT",
    "MAX_BODY_BYTES",
    "RSS_URL",
    "SOURCE",
    "PreseasonNewsClient",
    "PreseasonNewsFeed",
    "PreseasonNewsItem",
    "PreseasonNewsResolution",
    "PreseasonNewsSnapshot",
    "ResolvedPreseasonNewsItem",
    "UnresolvedPreseasonNewsItem",
    "parse_preseason_news",
    "resolve_preseason_news",
    "write_preseason_news_report",
]
