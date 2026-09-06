"""Strict parser for RotoWire's public NBA news RSS feed."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.preseason_news.models import PreseasonNewsFeed, PreseasonNewsItem
from hoops_gm.ingest.preseason_news.name_evidence import name_evidence_agrees

SOURCE: Final = "rotowire_nba_news"
ENDPOINT: Final = "latest_nba_news"
RSS_URL: Final = "https://www.rotowire.com/rss/news.php?sport=NBA"
MAX_BODY_BYTES: Final = 1_048_576
MAX_FUTURE_SKEW: Final = timedelta(minutes=5)

_CHANNEL_SINGLETON_TAGS: Final = frozenset(
    {"title", "copyright", "description", "category", "language", "ttl", "image", "link"}
)
_ITEM_TAGS: Final = frozenset({"guid", "title", "link", "description", "pubDate"})
_IMAGE_TAGS: Final = frozenset({"title", "width", "height", "link", "url"})
_GUID_PATTERN: Final = re.compile(r"nba[1-9][0-9]*\Z")
_PLAYER_PATH_PATTERN: Final = re.compile(r"(?P<slug>[a-z0-9-]+)-(?P<id>[1-9][0-9]*)\Z")
_PUBLISH_DATE_PATTERN: Final = re.compile(
    r"(?P<weekday>Mon|Tue|Wed|Thu|Fri|Sat|Sun), "
    r"(?P<body>[0-9]{2} [A-Z][a-z]{2} [0-9]{4} "
    r"[0-9]{1,2}:[0-9]{2}:[0-9]{2} (?:AM|PM)) "
    r"(?P<zone>PST|PDT)\Z"
)
_PACIFIC: Final = ZoneInfo("America/Los_Angeles")


def parse_preseason_news(body: bytes, *, observed_at: datetime) -> PreseasonNewsFeed:
    """Parse one exact HTTP body and reject structural or semantic contradictions."""
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    if not body:
        raise _contract_error("response body is empty")
    if len(body) > MAX_BODY_BYTES:
        raise _contract_error(
            f"response body is {len(body)} bytes, above the {MAX_BODY_BYTES}-byte limit"
        )

    lowered = body.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise _contract_error("DTD and entity declarations are not allowed in the RSS feed")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _contract_error("response body is not UTF-8 XML") from exc
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise _contract_error(f"response body is not well-formed XML: {exc}") from exc

    if root.tag != "rss" or root.attrib != {"version": "2.0"}:
        raise _contract_error('root must be exactly <rss version="2.0">')
    if len(root) != 1 or root[0].tag != "channel":
        raise _contract_error("rss must contain exactly one channel")
    channel = root[0]
    if channel.attrib:
        raise _contract_error("channel attributes changed")

    counts = Counter(child.tag for child in channel)
    expected_tags = _CHANNEL_SINGLETON_TAGS | {"item"}
    if set(counts) != expected_tags:
        raise _contract_error(
            "channel fields changed; "
            f"missing={sorted(expected_tags - set(counts))}, "
            f"unexpected={sorted(set(counts) - expected_tags)}"
        )
    duplicated = sorted(tag for tag in _CHANNEL_SINGLETON_TAGS if counts[tag] != 1)
    if duplicated:
        raise _contract_error(f"channel singleton fields changed: {duplicated}")
    if counts["item"] < 1:
        raise _contract_error("channel must contain at least one item")

    image = _single_child(channel, "image")
    _require_exact_child_tags(image, _IMAGE_TAGS, label="image")
    if image.attrib:
        raise _contract_error("image attributes changed")

    ttl_text = _single_text(channel, "ttl")
    if not ttl_text.isascii() or not ttl_text.isdigit():
        raise _contract_error(f"ttl must be an ASCII integer, got {ttl_text!r}")
    ttl_minutes = int(ttl_text)
    if not 1 <= ttl_minutes <= 60:
        raise _contract_error(f"ttl must be between 1 and 60 minutes, got {ttl_minutes}")

    feed_title = _single_text(channel, "title")
    if feed_title != "RotoWire.com Latest NBA News":
        raise _contract_error(f"channel title changed to {feed_title!r}")
    feed_link = _single_text(channel, "link")
    if feed_link != "https://www.rotowire.com":
        raise _contract_error(f"channel link changed to {feed_link!r}")
    copyright_text = _single_text(channel, "copyright")
    if not re.fullmatch(
        r"Copyright \(c\) [0-9]{4} Roto Sports, Inc, All rights reserved\.",
        copyright_text,
    ):
        raise _contract_error(f"copyright field changed to {copyright_text!r}")

    items = tuple(
        _parse_item(item, index=index, observed_at=observed_at)
        for index, item in enumerate(channel.findall("item"))
    )
    guids = [item.guid for item in items]
    if len(set(guids)) != len(guids):
        raise _contract_error("item guid values must be unique within a feed")
    published = [item.published_at for item in items]
    if published != sorted(published, reverse=True):
        raise _contract_error("items are no longer ordered newest first")

    return PreseasonNewsFeed(
        title=feed_title,
        copyright=copyright_text,
        description=_single_text(channel, "description"),
        category=_single_text(channel, "category"),
        language=_single_text(channel, "language"),
        ttl_minutes=ttl_minutes,
        link=feed_link,
        items=items,
    )


def _parse_item(item: ET.Element, *, index: int, observed_at: datetime) -> PreseasonNewsItem:
    _require_exact_child_tags(item, _ITEM_TAGS, label=f"item {index}")
    if item.attrib:
        raise _contract_error(f"item {index} attributes changed")

    guid = _single_text(item, "guid")
    if _GUID_PATTERN.fullmatch(guid) is None:
        raise _contract_error(f"item {index} guid changed shape: {guid!r}")

    raw_title = _single_text(item, "title")
    if ": " not in raw_title:
        raise _contract_error(f"item {index} title has no player/headline delimiter")
    player_name, headline = raw_title.split(": ", 1)
    if not player_name.strip() or not headline.strip():
        raise _contract_error(f"item {index} title has an empty player or headline")

    link = _single_text(item, "link")
    parsed_link = urlparse(link)
    path_parts = [part for part in parsed_link.path.split("/") if part]
    if (
        parsed_link.scheme != "https"
        or parsed_link.netloc != "www.rotowire.com"
        or parsed_link.params
        or parsed_link.query
        or parsed_link.fragment
        or len(path_parts) != 3
        or path_parts[:2] != ["basketball", "player"]
    ):
        raise _contract_error(f"item {index} link changed shape: {link!r}")
    player_match = _PLAYER_PATH_PATTERN.fullmatch(path_parts[2])
    if player_match is None:
        raise _contract_error(f"item {index} player link has no stable numeric id: {link!r}")
    slug_name = player_match.group("slug").replace("-", " ")
    if not name_evidence_agrees(slug_name, player_name):
        raise _contract_error(
            f"item {index} title player {player_name!r} contradicts link slug {slug_name!r}"
        )

    published_at_raw = _single_text(item, "pubDate")
    published_at = _parse_publish_date(published_at_raw, index=index)
    if published_at > observed_at.astimezone(UTC) + MAX_FUTURE_SKEW:
        raise _contract_error(
            f"item {index} pubDate {published_at_raw!r} is after the observation time"
        )

    return PreseasonNewsItem(
        guid=guid,
        rotowire_player_id=player_match.group("id"),
        player_name=player_name.strip(),
        headline=headline.strip(),
        description=_single_text(item, "description"),
        published_at=published_at,
        published_at_raw=published_at_raw,
        link=link,
    )


def _parse_publish_date(value: str, *, index: int) -> datetime:
    match = _PUBLISH_DATE_PATTERN.fullmatch(value)
    if match is None:
        raise _contract_error(f"item {index} pubDate changed shape: {value!r}")
    try:
        local = datetime.strptime(match.group("body"), "%d %b %Y %I:%M:%S %p")
    except ValueError as exc:
        raise _contract_error(f"item {index} pubDate is invalid: {value!r}") from exc
    if local.strftime("%a") != match.group("weekday"):
        raise _contract_error(f"item {index} pubDate weekday contradicts its calendar date")
    candidates: list[datetime] = []
    try:
        for fold in (0, 1):
            zoned = local.replace(tzinfo=_PACIFIC, fold=fold)
            round_trip = zoned.astimezone(UTC).astimezone(_PACIFIC)
            if (
                zoned.tzname() == match.group("zone")
                and round_trip.replace(tzinfo=None) == local
                and round_trip.fold == fold
            ):
                candidates.append(zoned)
    except (OverflowError, ValueError) as exc:
        raise _contract_error(f"item {index} pubDate is outside the supported range") from exc
    if len(candidates) != 1:
        raise _contract_error(
            f"item {index} pubDate zone {match.group('zone')!r} contradicts "
            "America/Los_Angeles for that date"
        )
    return candidates[0].astimezone(UTC)


def _require_exact_child_tags(element: ET.Element, expected: frozenset[str], *, label: str) -> None:
    counts = Counter(child.tag for child in element)
    if set(counts) != expected or any(count != 1 for count in counts.values()):
        raise _contract_error(
            f"{label} fields changed; missing={sorted(expected - set(counts))}, "
            f"unexpected={sorted(set(counts) - expected)}, duplicates="
            f"{sorted(tag for tag, count in counts.items() if count != 1)}"
        )


def _single_child(element: ET.Element, tag: str) -> ET.Element:
    matches = element.findall(tag)
    if len(matches) != 1:
        raise _contract_error(f"expected exactly one {tag!r} element")
    return matches[0]


def _single_text(element: ET.Element, tag: str) -> str:
    child = _single_child(element, tag)
    if child.attrib or len(child):
        raise _contract_error(f"{tag!r} must be a text-only element")
    value = child.text
    if value is None or not value.strip():
        raise _contract_error(f"{tag!r} must contain text")
    return value.strip()


def _contract_error(message: str) -> SourceContractError:
    return SourceContractError(message, source=SOURCE, endpoint=ENDPOINT)
