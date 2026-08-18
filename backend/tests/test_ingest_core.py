"""The adapter machinery: throttling, retry, raw capture, error classification.

None of this touches a network. The rate limiter and the retry policy take
their clock and their sleep as parameters precisely so that pacing arithmetic
can be asserted without spending real seconds — a limiter that can only be
tested by waiting is a limiter nobody tests.
"""

from __future__ import annotations

import gzip
import io
import json
import urllib.error
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from hoops_gm.ingest import (
    RateLimiter,
    RawPayloadStore,
    RetryPolicy,
    SourceContractError,
    SourceRejected,
    SourceUnavailable,
    call_with_retry,
    redact_params,
)
from hoops_gm.ingest.errors import CredentialsExpired, SourceError
from hoops_gm.ingest.fantrax_official import FantraxOfficialClient
from hoops_gm.ingest.nba.client import NbaStatsClient, _is_transport_failure
from hoops_gm.ingest.rawstore import canonical_params, request_key

#: Secret-shaped test values, bound to lower-case names rather than written
#: inline beside a `userSecretId` key. Inline, the scan reports them — which is
#: correct, and is what `test_secret_scan.py` asserts. Naming them also
#: exercises the suppression the way real adapter code does.
fake_secret = "abcdef1234567890secret"
other_fake_secret = "zyxwvu9876543210other"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


# ==========================================================================
# Throttling
# ==========================================================================


class TestRateLimiter:
    def test_the_first_acquisition_does_not_wait(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(1.1, monotonic=clock.monotonic, sleep=clock.sleep)
        assert limiter.acquire() == 0.0
        assert clock.slept == []

    def test_successive_acquisitions_are_spaced_by_the_interval(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(1.1, monotonic=clock.monotonic, sleep=clock.sleep)
        limiter.acquire()
        assert limiter.acquire() == pytest.approx(1.1)
        assert limiter.acquire() == pytest.approx(1.1)
        assert clock.slept == pytest.approx([1.1, 1.1])

    def test_a_slow_caller_is_not_delayed_further(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(1.1, monotonic=clock.monotonic, sleep=clock.sleep)
        limiter.acquire()
        clock.now += 5.0
        assert limiter.acquire() == 0.0

    def test_the_interval_does_not_creep_upward_over_a_long_backfill(self) -> None:
        """Advance from the scheduled slot, not from the post-sleep clock.

        Using "now" after sleeping adds the cost of each call to every
        interval. Over the ~2,460 requests in a season backfill that turns a
        20-minute job into a materially longer one, silently.
        """
        clock = FakeClock()
        limiter = RateLimiter(1.0, monotonic=clock.monotonic, sleep=clock.sleep)
        limiter.acquire()
        for _ in range(100):
            # Every call costs 10ms of work before asking for the next slot.
            clock.now += 0.01
            limiter.acquire()
        # 100 intervals of exactly 1.0s. Advancing from the post-sleep clock
        # instead would have added the 10ms per call, landing at 101.0.
        assert clock.now == pytest.approx(100.0, abs=0.001)

    def test_a_negative_interval_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            RateLimiter(-1.0)

    def test_reset_clears_the_pacing_state(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(1.1, monotonic=clock.monotonic, sleep=clock.sleep)
        limiter.acquire()
        limiter.reset()
        assert limiter.acquire() == 0.0


# ==========================================================================
# Retry
# ==========================================================================


class TestRetry:
    def test_a_retryable_failure_is_retried_and_can_succeed(self) -> None:
        clock = FakeClock()
        attempts: list[int] = []

        def flaky() -> str:
            attempts.append(1)
            if len(attempts) < 3:
                raise SourceUnavailable("timeout", source="test")
            return "ok"

        result = call_with_retry(
            flaky,
            policy=RetryPolicy(attempts=3, jitter=0.0),
            sleep=clock.sleep,
        )
        assert result == "ok"
        assert len(attempts) == 3
        assert clock.slept == pytest.approx([1.0, 2.0])

    def test_a_rejection_is_never_retried(self) -> None:
        """The request is wrong. Repeating it is rude and cannot succeed."""
        calls: list[int] = []

        def refused() -> None:
            calls.append(1)
            raise SourceRejected("missing leagueId", source="test")

        with pytest.raises(SourceRejected):
            call_with_retry(refused, policy=RetryPolicy(attempts=5), sleep=lambda _: None)
        assert len(calls) == 1

    def test_a_contract_error_is_never_retried(self) -> None:
        """Retrying around upstream drift delays the loud failure ADR-006
        exists to produce, and hammers a source we are meant to be gentle
        with."""
        calls: list[int] = []

        def drifted() -> None:
            calls.append(1)
            raise SourceContractError("shape changed", source="test")

        with pytest.raises(SourceContractError):
            call_with_retry(drifted, policy=RetryPolicy(attempts=5), sleep=lambda _: None)
        assert len(calls) == 1

    def test_the_last_failure_propagates_once_attempts_are_exhausted(self) -> None:
        with pytest.raises(SourceUnavailable):
            call_with_retry(
                lambda: (_ for _ in ()).throw(SourceUnavailable("down", source="test")),
                policy=RetryPolicy(attempts=2, jitter=0.0),
                sleep=lambda _: None,
            )

    def test_a_non_source_exception_propagates_untranslated(self) -> None:
        """An adapter is expected to have translated whatever its library
        threw. Anything untranslated is an adapter bug, and a retry loop makes
        it harder to find rather than easier."""
        with pytest.raises(ValueError):
            call_with_retry(
                lambda: (_ for _ in ()).throw(ValueError("bug")),
                policy=RetryPolicy(attempts=3),
                sleep=lambda _: None,
            )

    def test_backoff_is_exponential_and_capped(self) -> None:
        policy = RetryPolicy(
            base_delay_seconds=1.0, multiplier=2.0, max_delay_seconds=5.0, jitter=0.0
        )
        assert [policy.delay_for(n) for n in (2, 3, 4, 5, 6)] == [1.0, 2.0, 4.0, 5.0, 5.0]

    def test_jitter_stays_within_bounds_and_never_goes_negative(self) -> None:
        policy = RetryPolicy(base_delay_seconds=1.0, jitter=1.0, multiplier=1.0)
        for value in (0.0, 0.5, 1.0):

            def fixed(bound: float = value) -> float:
                return bound

            delay = policy.delay_for(2, rand=fixed)
            assert 0.0 <= delay <= 2.0

    def test_an_invalid_policy_is_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError):
            RetryPolicy(attempts=0)
        with pytest.raises(ValueError):
            RetryPolicy(jitter=1.5)

    def test_on_retry_is_told_which_attempt_failed_and_for_how_long_we_wait(self) -> None:
        seen: list[tuple[int, str, float]] = []

        def flaky() -> str:
            if len(seen) < 1:
                raise SourceUnavailable("boom", source="test", endpoint="thing")
            return "ok"

        call_with_retry(
            flaky,
            policy=RetryPolicy(attempts=2, jitter=0.0),
            on_retry=lambda attempt, exc, delay: seen.append((attempt, exc.source, delay)),
            sleep=lambda _: None,
        )
        assert seen == [(1, "test", 1.0)]


# ==========================================================================
# Errors
# ==========================================================================


class TestErrorTaxonomy:
    def test_only_unavailability_is_retryable(self) -> None:
        assert SourceUnavailable("x", source="s").retryable is True
        assert SourceRejected("x", source="s").retryable is False
        assert SourceContractError("x", source="s").retryable is False
        assert CredentialsExpired("x", source="s").retryable is False

    def test_expired_credentials_are_a_kind_of_rejection(self) -> None:
        """So a caller handling refusals generically still catches them, while
        one that wants to prompt for a re-login can single them out."""
        assert issubclass(CredentialsExpired, SourceRejected)
        assert issubclass(SourceRejected, SourceError)

    def test_the_source_and_endpoint_are_attributes_not_only_text(self) -> None:
        error = SourceUnavailable("boom", source="nba_stats", endpoint="PlayerGameLogs")
        assert error.source == "nba_stats"
        assert error.endpoint == "PlayerGameLogs"
        assert "nba_stats.PlayerGameLogs" in str(error)


# ==========================================================================
# Raw payload store
# ==========================================================================


class TestRawPayloadStore:
    def test_a_capture_round_trips(self, tmp_path: Path) -> None:
        store = RawPayloadStore(tmp_path)
        ref = store.put(
            source="fantrax_official",
            endpoint="getAdp",
            params={"sport": "NBA"},
            body=b'{"a": 1}',
            http_status=200,
        )
        assert ref.read_json() == {"a": 1}
        assert ref.byte_size == 8
        assert ref.path.suffix == ".gz"

    def test_the_body_is_stored_compressed(self, tmp_path: Path) -> None:
        store = RawPayloadStore(tmp_path)
        body = b'{"padding": "' + b"x" * 5000 + b'"}'
        ref = store.put(source="s", endpoint="e", params=None, body=body)
        assert ref.path.stat().st_size < len(body) / 10
        with gzip.open(ref.path, "rb") as handle:
            assert handle.read() == body

    def test_an_identical_payload_compresses_to_identical_bytes(self, tmp_path: Path) -> None:
        """So "did this response actually change" is a file comparison."""
        store = RawPayloadStore(tmp_path)
        body = b'{"a": 1}'
        first = store.put(
            source="s",
            endpoint="e",
            params=None,
            body=body,
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        second = store.put(
            source="s",
            endpoint="e",
            params=None,
            body=body,
            fetched_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        assert first.path.read_bytes() == second.path.read_bytes()

    def test_the_latest_capture_wins(self, tmp_path: Path) -> None:
        store = RawPayloadStore(tmp_path)
        params = {"sport": "NBA"}
        store.put(
            source="s",
            endpoint="e",
            params=params,
            body=b"1",
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        store.put(
            source="s",
            endpoint="e",
            params=params,
            body=b"2",
            fetched_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        latest = store.latest(source="s", endpoint="e", params=params)
        assert latest is not None
        assert latest.read_bytes() == b"2"
        assert len(store.history(source="s", endpoint="e", params=params)) == 2

    def test_freshness_respects_the_window(self, tmp_path: Path) -> None:
        store = RawPayloadStore(tmp_path)
        now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
        store.put(
            source="s",
            endpoint="e",
            params=None,
            body=b"1",
            fetched_at=now - timedelta(hours=3),
        )
        assert store.fresh(
            source="s", endpoint="e", params=None, max_age=timedelta(hours=6), now=now
        )
        assert not store.fresh(
            source="s", endpoint="e", params=None, max_age=timedelta(hours=1), now=now
        )

    def test_a_zero_window_always_misses(self, tmp_path: Path) -> None:
        """How a caller asks for a guaranteed live fetch without a second flag."""
        store = RawPayloadStore(tmp_path)
        store.put(source="s", endpoint="e", params=None, body=b"1")
        assert store.fresh(source="s", endpoint="e", params=None, max_age=timedelta(0)) is None

    def test_different_parameters_do_not_share_a_capture(self, tmp_path: Path) -> None:
        store = RawPayloadStore(tmp_path)
        store.put(source="s", endpoint="e", params={"sport": "NBA"}, body=b"nba")
        other = store.latest(source="s", endpoint="e", params={"sport": "NHL"})
        assert other is None

    def test_parameter_order_does_not_change_the_key(self, tmp_path: Path) -> None:
        assert request_key({"a": 1, "b": 2}) == request_key({"b": 2, "a": 1})
        assert canonical_params({"b": 2, "a": 1}) == '{"a":1,"b":2}'

    def test_every_capture_is_recorded_in_the_audit_index(self, tmp_path: Path) -> None:
        store = RawPayloadStore(tmp_path)
        store.put(source="s", endpoint="e", params={"x": 1}, body=b"1", http_status=200)
        store.put(source="s", endpoint="f", params=None, body=b"2", http_status=500)
        entries = store.index_entries("s")
        assert len(entries) == 2
        assert {e["endpoint"] for e in entries} == {"e", "f"}
        assert entries[0]["content_sha256"]

    def test_a_reconstructed_reference_does_not_claim_a_digest_it_lacks(
        self, tmp_path: Path
    ) -> None:
        """The filename carries a prefix only. Presenting it as the full digest
        would be a lie in the one component whose job is knowing exactly what
        was received."""
        store = RawPayloadStore(tmp_path)
        written = store.put(source="s", endpoint="e", params=None, body=b"hello")
        reloaded = store.latest(source="s", endpoint="e", params=None)
        assert reloaded is not None
        assert reloaded.content_sha256 is None
        assert reloaded.sha256() == written.content_sha256

    def test_pruning_is_explicit_and_never_a_side_effect_of_writing(self, tmp_path: Path) -> None:
        """The whole value of the store is still holding the payload from
        before the thing that broke."""
        store = RawPayloadStore(tmp_path)
        for day in range(1, 6):
            store.put(
                source="s",
                endpoint="e",
                params=None,
                body=str(day).encode(),
                fetched_at=datetime(2026, 1, day, tzinfo=UTC),
            )
        assert len(store.history(source="s", endpoint="e", params=None)) == 5
        removed = store.prune(source="s", endpoint="e", params=None, keep=2)
        assert removed == 3
        remaining = store.history(source="s", endpoint="e", params=None)
        assert [r.read_bytes() for r in remaining] == [b"4", b"5"]

    def test_a_credential_is_never_written_to_the_index(self, tmp_path: Path) -> None:
        """The index is plaintext, append-only, never pruned, and kept forever.

        Some league-scoped calls may carry a ``userSecretId``, and the same
        params dict reaches the store. Written verbatim, a live credential ends
        up in the same ``data/`` directory as the Fantrax cookie we went to the
        trouble of encrypting — which would make the encryption theatre.
        """
        store = RawPayloadStore(tmp_path)
        store.put(
            source="fantrax_official",
            endpoint="getLeagueInfo",
            params={"leagueId": "abc123", "userSecretId": fake_secret},
            body=b"{}",
        )

        index = (tmp_path / "fantrax_official" / "index.jsonl").read_text(encoding="utf-8")
        assert fake_secret not in index, "a live credential was written to the raw index"
        assert "<redacted>" in index
        # The non-secret parameter is still there: the index has to stay useful.
        assert "abc123" in index

    def test_redaction_does_not_change_cache_identity(self, tmp_path: Path) -> None:
        """``request_key`` hashes the real parameters, so a capture is still
        found by the request that produced it — and two requests differing only
        in their secret still hash differently."""
        store = RawPayloadStore(tmp_path)
        params = {"leagueId": "abc123", "userSecretId": fake_secret}
        store.put(source="s", endpoint="e", params=params, body=b"payload")

        assert store.latest(source="s", endpoint="e", params=params) is not None
        other = {**params, "userSecretId": other_fake_secret}
        assert store.latest(source="s", endpoint="e", params=other) is None

    @pytest.mark.parametrize(
        "key",
        [
            "userSecretId",
            "user_secret_id",
            "USER_SECRET_ID",
            "apiKey",
            "api_key",
            "token",
            "cookie",
            "password",
            "Authorization",
            "sessionId",
        ],
    )
    def test_every_credential_shaped_parameter_name_is_redacted(self, key: str) -> None:
        redacted = redact_params({key: "abcdef1234567890", "sport": "NBA"})
        assert redacted is not None
        assert redacted[key] == "<redacted>"
        assert redacted["sport"] == "NBA"

    def test_ordinary_parameters_survive_redaction(self) -> None:
        params = {"sport": "NBA", "season": "2024-25", "game_id": "0022400306"}
        assert redact_params(params) == params

    def test_a_naive_timestamp_is_rejected(self, tmp_path: Path) -> None:
        store = RawPayloadStore(tmp_path)
        with pytest.raises(ValueError, match="timezone-aware"):
            store.put(
                source="s",
                endpoint="e",
                params=None,
                body=b"1",
                fetched_at=datetime(2026, 1, 1),
            )

    def test_an_endpoint_name_cannot_escape_the_store_root(self, tmp_path: Path) -> None:
        store = RawPayloadStore(tmp_path)
        ref = store.put(source="s", endpoint="../../etc", params=None, body=b"1")
        assert tmp_path in ref.path.parents


# ==========================================================================
# Fantrax transport
# ==========================================================================


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200, content_type: str = "application/json"):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class TestFantraxTransport:
    def _client(self, opener: Any, **kwargs: Any) -> FantraxOfficialClient:
        return FantraxOfficialClient(
            limiter=RateLimiter(0.0),
            retry_policy=RetryPolicy(attempts=2, base_delay_seconds=0.0, jitter=0.0),
            opener=opener,
            **kwargs,
        )

    def test_a_successful_fetch_decodes_json(self) -> None:
        client = self._client(lambda _request, timeout: FakeResponse(b'{"ok": true}'))
        assert client.fetch_json("getAdp", {"sport": "NBA"}) == {"ok": True}

    def test_the_request_carries_a_user_agent(self) -> None:
        """Fantrax answers **HTTP 403** to the default ``urllib`` User-Agent —
        found while recording the fixtures. Without these headers every
        endpoint on this source is unreachable."""
        seen: list[Any] = []

        def opener(request: Any, timeout: float) -> FakeResponse:
            seen.append(request)
            return FakeResponse(b"{}")

        self._client(opener).fetch_json("getAdp", {})
        assert seen
        agent = seen[0].get_header("User-agent")
        assert agent and "hoops-gm" in agent

    def test_a_non_json_body_is_a_contract_error(self) -> None:
        client = self._client(lambda _r, timeout: FakeResponse(b"<html>nope</html>"))
        with pytest.raises(SourceContractError, match="not JSON"):
            client.fetch_json("getAdp", {})

    def test_a_403_is_a_rejection_not_a_contract_error(self) -> None:
        """The source answered coherently and refused. Conflating that with
        drift makes a mistyped league id look like an upstream change."""

        def opener(_request: Any, timeout: float) -> FakeResponse:
            raise urllib.error.HTTPError("u", 403, "Forbidden", Message(), None)

        with pytest.raises(SourceRejected):
            self._client(opener).fetch_json("getAdp", {})

    def test_a_401_names_the_remedy(self) -> None:
        def opener(_request: Any, timeout: float) -> FakeResponse:
            raise urllib.error.HTTPError("u", 401, "Unauthorized", Message(), None)

        with pytest.raises(CredentialsExpired):
            self._client(opener).fetch_json("getLeagueInfo", {})

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_a_transient_status_is_unavailability_and_is_retried(self, status: int) -> None:
        calls: list[int] = []

        def opener(_request: Any, timeout: float) -> FakeResponse:
            calls.append(1)
            raise urllib.error.HTTPError("u", status, "later", Message(), None)

        with pytest.raises(SourceUnavailable):
            self._client(opener).fetch_json("getAdp", {})
        assert len(calls) == 2, "the policy allows two attempts"

    def test_a_network_failure_is_unavailability(self) -> None:
        def opener(_request: Any, timeout: float) -> FakeResponse:
            raise urllib.error.URLError("no route to host")

        with pytest.raises(SourceUnavailable, match="could not reach"):
            self._client(opener).fetch_json("getAdp", {})

    def test_the_raw_body_is_captured_before_it_is_decoded(self, tmp_path: Path) -> None:
        """A body that fails to parse is exactly the body worth still having."""
        store = RawPayloadStore(tmp_path)
        client = self._client(lambda _r, timeout: FakeResponse(b"not json"), store=store)
        with pytest.raises(SourceContractError):
            client.fetch_json("getAdp", {"sport": "NBA"})
        captured = store.latest(
            source="fantrax_official", endpoint="getAdp", params={"sport": "NBA"}
        )
        assert captured is not None
        assert captured.read_bytes() == b"not json"

    def test_a_fresh_capture_is_used_instead_of_a_request(self, tmp_path: Path) -> None:
        store = RawPayloadStore(tmp_path)
        store.put(
            source="fantrax_official",
            endpoint="getAdp",
            params={"sport": "NBA"},
            body=b'{"cached": true}',
        )
        calls: list[int] = []

        def opener(_request: Any, timeout: float) -> FakeResponse:
            calls.append(1)
            return FakeResponse(b'{"cached": false}')

        client = self._client(opener, store=store)
        assert client.fetch_json("getAdp", {"sport": "NBA"}) == {"cached": True}
        assert calls == []

    def test_the_adp_limit_is_passed_through_uncorrected(self) -> None:
        """The endpoint returns ``limit - 1`` rows. Silently adding one would
        hide an upstream fix and make our behaviour depend on when the caller
        last read a docstring."""
        seen: list[str] = []

        def opener(request: Any, timeout: float) -> FakeResponse:
            seen.append(request.full_url)
            return FakeResponse(b'[{"id": "x", "name": "N", "pos": "PG", "ADP": 1.0}]')

        self._client(opener).get_adp(limit=5)
        assert "limit=5" in seen[0]

    def test_get_league_info_sends_only_the_league_id_without_configured_secret(
        self,
    ) -> None:
        seen: list[str] = []

        def opener(request: Any, timeout: float) -> FakeResponse:
            seen.append(request.full_url)
            return FakeResponse(
                b'{"seasonYear": 2025, "startDate": "2025-10-21", '
                b'"endDate": "2026-03-15", "rosterInfo": {"maxTotalPlayers": 14}, '
                b'"scoringPeriods": [{"number": 1, "startDate": "2025-10-21", '
                b'"endDate": "2025-10-26"}]}'
            )

        result = self._client(opener).get_league_info("non-secret-id")

        assert result.settings is not None
        assert "leagueId=non-secret-id" in seen[0]
        assert "userSecretId" not in seen[0]


# ==========================================================================
# nba_api transport
# ==========================================================================


class TestNbaTransport:
    def test_a_library_parse_failure_becomes_a_contract_error_naming_the_endpoint(
        self,
    ) -> None:
        """``nba_api`` does not fail cleanly on a bad request: a nonexistent
        game id produces ``AttributeError: 'NoneType' object has no attribute
        'get'`` from inside the library. Unwrapped, that appears in a backfill
        log with no indication of which endpoint or which game."""

        class Exploding:
            def get_dict(self) -> Any:
                raise AttributeError("'NoneType' object has no attribute 'get'")

        client = NbaStatsClient(
            limiter=RateLimiter(0.0),
            retry_policy=RetryPolicy(attempts=1),
            endpoint_factory=lambda endpoint, **kwargs: Exploding(),
        )
        with pytest.raises(SourceContractError) as caught:
            client.box_score_summary("0099999999")
        assert "BoxScoreSummaryV3" in str(caught.value)
        assert caught.value.detail == {"game_id": "0099999999"}

    def test_a_transport_failure_is_classified_as_unavailable_and_retried(self) -> None:
        calls: list[int] = []

        class Timeout(Exception):
            pass

        Timeout.__name__ = "ReadTimeout"

        class Slow:
            def get_dict(self) -> Any:
                calls.append(1)
                raise Timeout("too slow")

        client = NbaStatsClient(
            limiter=RateLimiter(0.0),
            retry_policy=RetryPolicy(attempts=3, base_delay_seconds=0.0, jitter=0.0),
            endpoint_factory=lambda endpoint, **kwargs: Slow(),
        )
        with pytest.raises(SourceUnavailable):
            client.box_score_summary("0022400306")
        assert len(calls) == 3

    def test_transport_exceptions_are_recognised_by_name(self) -> None:
        assert _is_transport_failure(OSError("socket"))
        assert not _is_transport_failure(AttributeError("shape"))

    def test_a_completed_game_is_served_from_cache_forever(self, tmp_path: Path) -> None:
        """A finished box score is immutable, which is what makes a
        2,460-request season backfill resumable rather than restartable."""
        store = RawPayloadStore(tmp_path)
        store.put(
            source="nba_stats",
            endpoint="BoxScoreSummaryV3",
            params={"game_id": "0022400306"},
            body=json.dumps({"cached": True}).encode(),
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        calls: list[int] = []

        def factory(endpoint: str, **kwargs: Any) -> Any:
            calls.append(1)
            raise AssertionError("should not have been called")

        client = NbaStatsClient(store=store, limiter=RateLimiter(0.0), endpoint_factory=factory)
        assert client.box_score_summary("0022400306") == {"cached": True}
        assert calls == []

    def test_the_response_is_captured(self, tmp_path: Path) -> None:
        store = RawPayloadStore(tmp_path)

        class Fine:
            def get_dict(self) -> Any:
                return {"boxScoreSummary": {"gameId": "1"}}

        client = NbaStatsClient(
            store=store,
            limiter=RateLimiter(0.0),
            endpoint_factory=lambda endpoint, **kwargs: Fine(),
        )
        client.box_score_summary("0022400306")
        captured = store.latest(
            source="nba_stats",
            endpoint="BoxScoreSummaryV3",
            params={"game_id": "0022400306"},
        )
        assert captured is not None
        assert captured.read_json() == {"boxScoreSummary": {"gameId": "1"}}

    def test_boxscoresummaryv2_is_not_reachable_through_this_client(self) -> None:
        """Deliberately unexposed. Its inactive list silently returned zero
        rows for every 2025-26 date after opening night, and an endpoint that
        answers "nobody was inactive" when it means "I no longer know" is worse
        than one that fails outright."""
        from hoops_gm.ingest.nba.client import _default_endpoint_factory

        with pytest.raises(SourceContractError):
            _default_endpoint_factory("BoxScoreSummaryV2", game_id="0022400306")
