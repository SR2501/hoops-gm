"""Offline Adapter-gate coverage for preseason NBA player news."""

from __future__ import annotations

import gzip
import hashlib
import http.client
import io
import json
import urllib.error
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session

from hoops_gm.db.models import ExternalSource, MatchMethod, Player, PlayerExternalId
from hoops_gm.ingest.errors import SourceContractError, SourceRejected
from hoops_gm.ingest.preseason_news import (
    ENDPOINT,
    RSS_URL,
    SOURCE,
    PreseasonNewsClient,
    parse_preseason_news,
    resolve_preseason_news,
    write_preseason_news_report,
)
from hoops_gm.ingest.preseason_news import cli as preseason_news_cli
from hoops_gm.ingest.preseason_news.models import (
    PreseasonNewsFeed,
    PreseasonNewsResolution,
    PreseasonNewsSnapshot,
    ResolvedPreseasonNewsItem,
    UnresolvedPreseasonNewsItem,
)
from hoops_gm.ingest.preseason_news.name_evidence import name_evidence_key
from hoops_gm.ingest.rawstore import RawPayloadStore
from hoops_gm.ingest.retry import RetryPolicy
from hoops_gm.ingest.throttle import RateLimiter

pytestmark = pytest.mark.adapter_contract

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_NAME = "rotowire_nba_news.xml.gz"
FIXTURE_SHA256 = "0650edfe710f53f571573e1a3a9dae852c93c4bb8b9d0c3e48a1151f04b949a2"


def load_fixture_bytes() -> bytes:
    with gzip.open(FIXTURES / FIXTURE_NAME, "rb") as handle:
        return handle.read()


def fixture_observed_at() -> datetime:
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    return datetime.fromisoformat(manifest[FIXTURE_NAME]["captured_at"])


def parse_fixture() -> PreseasonNewsFeed:
    return parse_preseason_news(load_fixture_bytes(), observed_at=fixture_observed_at())


def mutate_fixture(old: bytes, new: bytes) -> bytes:
    body = load_fixture_bytes()
    assert old in body, "mutation anchor drifted; this is a failed mutation, not a pass"
    mutated = body.replace(old, new, 1)
    assert mutated != body
    return mutated


class TestPreseasonNewsContract:
    def test_fixture_is_the_exact_full_response_body(self) -> None:
        body = load_fixture_bytes()
        assert len(body) == 1632
        assert hashlib.sha256(body).hexdigest() == FIXTURE_SHA256

    def test_feed_matches_the_observed_contract(self) -> None:
        feed = parse_fixture()

        assert feed.title == "RotoWire.com Latest NBA News"
        assert feed.ttl_minutes == 10
        assert len(feed.items) == 2
        assert [(item.guid, item.rotowire_player_id, item.player_name) for item in feed.items] == [
            ("nba532524", "3014", "Stephen Curry"),
            ("nba532515", "3849", "Ben Simmons"),
        ]
        assert feed.items[0].published_at == datetime(2026, 9, 5, 18, 21, tzinfo=UTC)
        assert feed.items[0].published_at > feed.items[1].published_at

    def test_description_is_preserved_without_becoming_a_status_code(self) -> None:
        item = parse_fixture().items[0]

        assert "right knee" in item.description
        assert "&amp;" in item.description
        assert item.headline == "'Some lingering concern' about knee"
        assert not hasattr(item, "status")

    def test_missing_or_added_item_fields_fail_loudly(self) -> None:
        missing = mutate_fixture(b"        <guid>nba532524</guid>\n", b"")
        with pytest.raises(SourceContractError, match=r"missing=.*guid"):
            parse_preseason_news(missing, observed_at=fixture_observed_at())

        added = mutate_fixture(
            b"        <guid>nba532524</guid>\n",
            b"        <guid>nba532524</guid>\n        <team>GSW</team>\n",
        )
        with pytest.raises(SourceContractError, match=r"unexpected=.*team"):
            parse_preseason_news(added, observed_at=fixture_observed_at())

    def test_title_player_must_agree_with_the_link_slug(self) -> None:
        mutated = mutate_fixture(b"stephen-curry-3014", b"seth-curry-3014")

        with pytest.raises(SourceContractError, match="contradicts link slug"):
            parse_preseason_news(mutated, observed_at=fixture_observed_at())

    def test_title_and_link_cannot_disagree_only_by_suffix(self) -> None:
        mutated = mutate_fixture(b"stephen-curry-3014", b"stephen-curry-jr-3014")

        with pytest.raises(SourceContractError, match="contradicts link slug"):
            parse_preseason_news(mutated, observed_at=fixture_observed_at())

    def test_dotted_initials_agree_with_unpunctuated_link_slug(self) -> None:
        body = mutate_fixture(b"Stephen Curry", b"P.J. Washington")
        body = body.replace(b"stephen-curry-3014", b"pj-washington-4781", 1)

        feed = parse_preseason_news(body, observed_at=fixture_observed_at())

        assert feed.items[0].player_name == "P.J. Washington"
        assert feed.items[0].rotowire_player_id == "4781"

    def test_name_evidence_key_retains_one_sided_suffix(self) -> None:
        assert name_evidence_key("P.J. Washington") == name_evidence_key("pj washington")
        assert name_evidence_key("Kenyon Martin") != name_evidence_key("Kenyon Martin Jr.")

    def test_timezone_label_must_agree_with_the_calendar(self) -> None:
        mutated = mutate_fixture(
            b"Sat, 05 Sep 2026 11:21:00 AM PDT",
            b"Sat, 05 Sep 2026 11:21:00 AM PST",
        )

        with pytest.raises(SourceContractError, match="contradicts America/Los_Angeles"):
            parse_preseason_news(mutated, observed_at=fixture_observed_at())

    def test_valid_fall_back_fold_is_selected_by_its_zone_label(self) -> None:
        mutated = mutate_fixture(
            b"Sat, 05 Sep 2026 11:21:00 AM PDT",
            b"Sun, 01 Nov 2026 1:30:00 AM PST",
        )

        feed = parse_preseason_news(mutated, observed_at=datetime(2026, 11, 2, tzinfo=UTC))

        assert feed.items[0].published_at == datetime(2026, 11, 1, 9, 30, tzinfo=UTC)

    def test_nonexistent_spring_forward_wall_time_is_rejected(self) -> None:
        mutated = mutate_fixture(
            b"Sat, 05 Sep 2026 11:21:00 AM PDT",
            b"Sun, 08 Mar 2026 2:30:00 AM PST",
        )

        with pytest.raises(SourceContractError, match="contradicts America/Los_Angeles"):
            parse_preseason_news(mutated, observed_at=fixture_observed_at())

    def test_extreme_calendar_date_is_a_contract_error(self) -> None:
        mutated = mutate_fixture(
            b"Sat, 05 Sep 2026 11:21:00 AM PDT",
            b"Fri, 31 Dec 9999 11:59:59 PM PST",
        )

        with pytest.raises(SourceContractError, match="outside the supported range"):
            parse_preseason_news(mutated, observed_at=datetime.max.replace(tzinfo=UTC))

    def test_publication_time_cannot_postdate_the_observation(self) -> None:
        mutated = mutate_fixture(
            b"Sat, 05 Sep 2026 11:21:00 AM PDT",
            b"Sun, 06 Sep 2026 11:21:00 AM PDT",
        )

        with pytest.raises(SourceContractError, match="after the observation time"):
            parse_preseason_news(mutated, observed_at=fixture_observed_at())

    def test_xml_entity_declarations_are_rejected_before_parsing(self) -> None:
        mutated = mutate_fixture(
            b'<rss version="2.0">',
            b'<!DOCTYPE rss [<!ENTITY x "news">]><rss version="2.0">',
        )

        with pytest.raises(SourceContractError, match="DTD and entity"):
            parse_preseason_news(mutated, observed_at=fixture_observed_at())

    def test_feed_order_is_part_of_the_latest_news_contract(self) -> None:
        mutated = mutate_fixture(
            b"Sat, 05 Sep 2026 11:21:00 AM PDT",
            b"Thu, 03 Sep 2026 11:21:00 AM PDT",
        )

        with pytest.raises(SourceContractError, match="newest first"):
            parse_preseason_news(mutated, observed_at=fixture_observed_at())


def _crosswalk_link(
    session: Session,
    *,
    external_id: str,
    external_name: str,
    current: bool = True,
) -> Player:
    player = Player(full_name=external_name, normalized_name=external_name.lower())
    session.add(player)
    session.flush()
    session.add(
        PlayerExternalId(
            player_id=player.id,
            source=ExternalSource.FANTRAX_ROTOWIRE,
            current_for_source=(ExternalSource.FANTRAX_ROTOWIRE.value if current else None),
            external_id=external_id,
            external_name=external_name,
            normalized_name=external_name.lower(),
            confidence=1.0,
            match_method=MatchMethod.NORMALIZED_NAME,
        )
    )
    session.flush()
    return player


class TestPreseasonNewsIdentity:
    def test_exact_rotowire_id_resolves_through_the_existing_crosswalk(
        self, session: Session
    ) -> None:
        curry = _crosswalk_link(
            session,
            external_id="3014",
            external_name="Curry, Stephen",
        )
        _crosswalk_link(
            session,
            external_id="9999",
            external_name="Other Player",
        )

        result = resolve_preseason_news(session, parse_fixture().items)

        assert [(entry.item.guid, entry.player_id) for entry in result.resolved] == [
            ("nba532524", curry.id)
        ]
        assert len(result.unresolved) == 1
        assert "3849" in result.unresolved[0].reason

    def test_crosswalk_name_is_an_independent_veto_not_a_second_matcher(
        self, session: Session
    ) -> None:
        _crosswalk_link(
            session,
            external_id="3014",
            external_name="Seth Curry",
        )

        result = resolve_preseason_news(session, parse_fixture().items[:1])

        assert result.resolved == ()
        assert "contradicts crosswalk name" in result.unresolved[0].reason

    def test_crosswalk_name_with_one_sided_suffix_is_unresolved(self, session: Session) -> None:
        _crosswalk_link(
            session,
            external_id="3014",
            external_name="Stephen Curry Jr.",
        )

        result = resolve_preseason_news(session, parse_fixture().items[:1])

        assert result.resolved == ()
        assert "contradicts crosswalk name" in result.unresolved[0].reason

    def test_superseded_rotowire_id_is_not_joined(self, session: Session) -> None:
        _crosswalk_link(
            session,
            external_id="3014",
            external_name="Stephen Curry",
            current=False,
        )
        _crosswalk_link(
            session,
            external_id="9999",
            external_name="Other Player",
        )

        result = resolve_preseason_news(session, parse_fixture().items[:1])

        assert result.resolved == ()
        assert "no current" in result.unresolved[0].reason

    def test_missing_crosswalk_is_a_prerequisite_failure(self, session: Session) -> None:
        with pytest.raises(RuntimeError, match=r"run .* crosswalk"):
            resolve_preseason_news(session, parse_fixture().items)

    def test_report_keeps_resolved_and_unresolved_rows_visible(
        self, session: Session, tmp_path: Path
    ) -> None:
        _crosswalk_link(
            session,
            external_id="3014",
            external_name="Stephen Curry",
        )
        client = PreseasonNewsClient(
            store=RawPayloadStore(tmp_path / "raw"),
            limiter=RateLimiter(0),
            opener=FakeOpener(FakeResponse(load_fixture_bytes())),
        )
        snapshot = client.latest(max_age=timedelta(0))
        resolution = resolve_preseason_news(session, snapshot.feed.items)
        report_path = tmp_path / "reports" / "news.json"

        write_preseason_news_report(
            report_path,
            snapshot=snapshot,
            resolution=resolution,
        )

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["source_payload_sha256"] == FIXTURE_SHA256
        assert report["resolved_count"] == 1
        assert report["unresolved_count"] == 1
        assert report["items"][0]["identity_source"] == "fantrax_rotowire"
        assert report["unresolved"][0]["rotowire_player_id"] == "3849"


class FakeResponse:
    status = 200

    def __init__(
        self,
        body: bytes,
        *,
        content_type: str = "application/xml",
        status: int = 200,
    ) -> None:
        self.body = body
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


class FakeOpener:
    def __init__(self, *outcomes: Exception | FakeResponse) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, request: Any, **kwargs: Any) -> FakeResponse:
        del request, kwargs
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class IncompleteErrorBody(io.BytesIO):
    def __init__(self, partial: bytes) -> None:
        super().__init__(partial)
        self.partial = partial

    def read(self, size: int | None = -1) -> bytes:
        del size
        raise http.client.IncompleteRead(self.partial, 100)


class TestPreseasonNewsTransport:
    def test_fresh_raw_capture_is_reused(self, tmp_path: Path) -> None:
        opener = FakeOpener(FakeResponse(load_fixture_bytes()))
        client = PreseasonNewsClient(
            store=RawPayloadStore(tmp_path),
            limiter=RateLimiter(0),
            opener=opener,
        )

        first = client.latest()
        second = client.latest()

        assert first.source_payload_sha256 == FIXTURE_SHA256
        assert second.source_payload_sha256 == FIXTURE_SHA256
        assert opener.calls == 1

    def test_html_under_http_200_is_captured_and_rejected(self, tmp_path: Path) -> None:
        body = b"<html>not a feed</html>"
        store = RawPayloadStore(tmp_path)
        client = PreseasonNewsClient(
            store=store,
            limiter=RateLimiter(0),
            opener=FakeOpener(FakeResponse(body, content_type="text/html")),
        )

        with pytest.raises(SourceContractError, match="Content-Type"):
            client.latest(max_age=timedelta(0))

        captures = store.history(
            source=SOURCE,
            endpoint=f"{ENDPOINT}.contract_error",
            params={"url": RSS_URL},
        )
        assert len(captures) == 1
        assert captures[0].read_bytes() == body

    def test_non_retryable_http_refusal_is_explicit(self, tmp_path: Path) -> None:
        headers = Message()
        headers["Content-Type"] = "text/html"
        error = urllib.error.HTTPError(
            RSS_URL,
            403,
            "Forbidden",
            headers,
            io.BytesIO(b"forbidden"),
        )
        opener = FakeOpener(error)
        client = PreseasonNewsClient(
            store=RawPayloadStore(tmp_path),
            limiter=RateLimiter(0),
            opener=opener,
        )

        with pytest.raises(SourceRejected) as caught:
            client.latest(max_age=timedelta(0))

        assert caught.value.status_code == 403
        assert opener.calls == 1

    def test_retryable_http_failure_is_retried(self) -> None:
        headers = Message()
        headers["Content-Type"] = "text/html"
        error = urllib.error.HTTPError(
            RSS_URL,
            503,
            "Unavailable",
            headers,
            io.BytesIO(b"try later"),
        )
        opener = FakeOpener(error, FakeResponse(load_fixture_bytes()))
        client = PreseasonNewsClient(
            limiter=RateLimiter(0),
            retry_policy=RetryPolicy(attempts=2, base_delay_seconds=0, jitter=0),
            opener=opener,
        )

        snapshot = client.latest(max_age=timedelta(0))

        assert len(snapshot.feed.items) == 2
        assert opener.calls == 2

    def test_http_protocol_failure_is_retried(self) -> None:
        opener = FakeOpener(
            http.client.BadStatusLine("bad status"),
            FakeResponse(load_fixture_bytes()),
        )
        client = PreseasonNewsClient(
            limiter=RateLimiter(0),
            retry_policy=RetryPolicy(attempts=2, base_delay_seconds=0, jitter=0),
            opener=opener,
        )

        snapshot = client.latest(max_age=timedelta(0))

        assert len(snapshot.feed.items) == 2
        assert opener.calls == 2

    def test_truncated_http_error_body_preserves_partial_evidence(self, tmp_path: Path) -> None:
        headers = Message()
        headers["Content-Type"] = "text/html"
        partial = b"partial upstream refusal"
        error = urllib.error.HTTPError(
            RSS_URL,
            403,
            "Forbidden",
            headers,
            IncompleteErrorBody(partial),
        )
        store = RawPayloadStore(tmp_path)
        client = PreseasonNewsClient(
            store=store,
            limiter=RateLimiter(0),
            opener=FakeOpener(error),
        )

        with pytest.raises(SourceRejected):
            client.latest(max_age=timedelta(0))

        captures = store.history(
            source=SOURCE,
            endpoint=f"{ENDPOINT}.http_error_incomplete_read",
            params={"url": RSS_URL},
        )
        assert len(captures) == 1
        assert captures[0].read_bytes() == partial

    def test_actual_body_length_not_content_length_enforces_the_bound(self, tmp_path: Path) -> None:
        body = b"x" * (1_048_576 + 1)
        store = RawPayloadStore(tmp_path)
        client = PreseasonNewsClient(
            store=store,
            limiter=RateLimiter(0),
            opener=FakeOpener(FakeResponse(body)),
        )

        with pytest.raises(SourceContractError, match="exceeded"):
            client.latest(max_age=timedelta(0))

        captures = store.history(
            source=SOURCE,
            endpoint=f"{ENDPOINT}.contract_error",
            params={"url": RSS_URL},
        )
        assert len(captures[0].read_bytes()) == len(body)


class FakeDatabase:
    def __init__(self) -> None:
        self.disposed = False

    def session(self) -> AbstractContextManager[object]:
        return nullcontext(object())

    def dispose(self) -> None:
        self.disposed = True


@pytest.mark.parametrize(("has_unresolved", "expected_exit"), [(False, 0), (True, 2)])
def test_cli_exit_reflects_identity_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    has_unresolved: bool,
    expected_exit: int,
) -> None:
    feed = parse_fixture()
    item = feed.items[0]
    snapshot = PreseasonNewsSnapshot(
        feed=feed,
        observed_at=fixture_observed_at(),
        source_payload_sha256=FIXTURE_SHA256,
    )
    resolution = PreseasonNewsResolution(
        resolved=(
            ()
            if has_unresolved
            else (
                ResolvedPreseasonNewsItem(
                    item=item,
                    player_id=1,
                    crosswalk_external_name="Stephen Curry",
                ),
            )
        ),
        unresolved=(
            (UnresolvedPreseasonNewsItem(item=item, reason="missing test crosswalk"),)
            if has_unresolved
            else ()
        ),
    )
    database = FakeDatabase()
    written: list[Path] = []

    class FakeDatabaseFactory:
        @staticmethod
        def from_settings(settings: Any) -> FakeDatabase:
            del settings
            return database

    class FakeNewsClient:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

        def latest(self) -> PreseasonNewsSnapshot:
            return snapshot

    def fake_write_report(
        path: Path,
        *,
        snapshot: PreseasonNewsSnapshot,
        resolution: PreseasonNewsResolution,
    ) -> None:
        del snapshot, resolution
        written.append(path)

    monkeypatch.setattr(
        preseason_news_cli,
        "get_settings",
        lambda: SimpleNamespace(database_url="sqlite:///unused.db"),
    )
    monkeypatch.setattr(preseason_news_cli, "absent_store_refusal", lambda _url: None)
    monkeypatch.setattr(preseason_news_cli, "Database", FakeDatabaseFactory)
    monkeypatch.setattr(preseason_news_cli, "PreseasonNewsClient", FakeNewsClient)
    monkeypatch.setattr(
        preseason_news_cli,
        "resolve_preseason_news",
        lambda _session, _items: resolution,
    )
    monkeypatch.setattr(preseason_news_cli, "write_preseason_news_report", fake_write_report)
    output = tmp_path / "news.json"

    exit_code = preseason_news_cli.main(["--output", str(output)])

    assert exit_code == expected_exit
    assert database.disposed
    assert written == [output]
