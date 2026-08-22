"""Ingesting published auction values — the market layer's adapter.

``aav-source``. Sources and stores what other people published, with
provenance. Derives nothing: see ``db/models/market.py`` for why that boundary
is where it is, and ``hoops_gm.market.independence`` for the rule that decides
whether a stored source may be used as a benchmark.
"""

from __future__ import annotations

from hoops_gm.ingest.auction_values.models import (
    AuctionValueParseResult,
    AuctionValueRowIssue,
    PublishedValueRow,
)
from hoops_gm.ingest.auction_values.parser import (
    AuctionValueProfileError,
    parse_auction_value_csv,
)
from hoops_gm.ingest.auction_values.profiles import (
    AUCTION_VALUE_PROFILES,
    AUCTION_VALUE_SOURCES,
    AuctionSourceDescriptor,
    AuctionValueProfile,
    SourceInputDescriptor,
    ValueColumn,
    profile_for,
    source_for,
)

__all__ = [
    "AUCTION_VALUE_PROFILES",
    "AUCTION_VALUE_SOURCES",
    "AuctionSourceDescriptor",
    "AuctionValueParseResult",
    "AuctionValueProfile",
    "AuctionValueProfileError",
    "AuctionValueRowIssue",
    "PublishedValueRow",
    "SourceInputDescriptor",
    "ValueColumn",
    "parse_auction_value_csv",
    "profile_for",
    "source_for",
]
