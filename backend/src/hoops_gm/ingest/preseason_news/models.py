"""Typed records from the preseason news feed and its identity join."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PreseasonNewsItem:
    """One source item, with prose preserved and no inferred availability status."""

    guid: str
    rotowire_player_id: str
    player_name: str
    headline: str
    description: str
    published_at: datetime
    published_at_raw: str
    link: str


@dataclass(frozen=True)
class PreseasonNewsFeed:
    """The RSS channel metadata and its ordered items."""

    title: str
    copyright: str
    description: str
    category: str
    language: str
    ttl_minutes: int
    link: str
    items: tuple[PreseasonNewsItem, ...]


@dataclass(frozen=True)
class PreseasonNewsSnapshot:
    """One byte-identifiable observation of the live feed."""

    feed: PreseasonNewsFeed
    observed_at: datetime
    source_payload_sha256: str


@dataclass(frozen=True)
class ResolvedPreseasonNewsItem:
    """A news item attached through the existing RotoWire crosswalk namespace."""

    item: PreseasonNewsItem
    player_id: int
    crosswalk_external_name: str


@dataclass(frozen=True)
class UnresolvedPreseasonNewsItem:
    """A news item deliberately withheld from downstream player joins."""

    item: PreseasonNewsItem
    reason: str


@dataclass(frozen=True)
class PreseasonNewsResolution:
    """Resolved and refused items from one feed observation."""

    resolved: tuple[ResolvedPreseasonNewsItem, ...]
    unresolved: tuple[UnresolvedPreseasonNewsItem, ...]
