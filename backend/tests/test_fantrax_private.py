"""The Fantrax private adapter: cookie storage and error translation.

Everything testable about this adapter is here, and it is a short list —
**no call has ever been made against `/fxpa/req`**, because no league id and no
session cookie existed when it was written. What is tested is what exists: the
encrypted cookie store, and the translation of ``fantraxapi``'s exceptions into
this project's vocabulary.

Parsers for roster, standings and matchup payloads are deliberately absent. See
``docs/adapters/fantrax-private.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hoops_gm.ingest.errors import (
    CredentialsExpired,
    SourceContractError,
    SourceUnavailable,
)
from hoops_gm.ingest.fantrax_private import (
    COOKIE_NAME,
    KEY_ENV_VAR,
    CookieStore,
    CookieStoreError,
    FantraxPrivateClient,
    build_session,
    generate_key,
)
from hoops_gm.ingest.retry import RetryPolicy
from hoops_gm.ingest.throttle import RateLimiter

COOKIE = "abc123def456ghi789"


@pytest.fixture
def store(tmp_path: Path) -> CookieStore:
    return CookieStore(path=tmp_path / "cookie.enc", key=generate_key())


class TestCookieStore:
    def test_a_cookie_round_trips(self, store: CookieStore) -> None:
        store.write(COOKIE)
        assert store.read() == COOKIE

    def test_the_cookie_is_not_readable_on_disk(self, store: CookieStore) -> None:
        """The whole point. A cookie in plaintext under data/ is a credential
        sitting in a directory people copy around."""
        store.write(COOKIE)
        raw = store.path.read_bytes()
        assert COOKIE.encode() not in raw
        assert raw != COOKIE.encode()

    def test_reading_with_the_wrong_key_fails_loudly(self, tmp_path: Path) -> None:
        original = CookieStore(path=tmp_path / "cookie.enc", key=generate_key())
        original.write(COOKIE)

        rotated = CookieStore(path=original.path, key=generate_key())
        with pytest.raises(CookieStoreError, match="could not decrypt"):
            rotated.read()

    def test_no_stored_cookie_is_reported_as_expired_credentials(self, store: CookieStore) -> None:
        """From the caller's point of view "no cookie" and "stale cookie" need
        the same action from the same person, so they get the same class."""
        with pytest.raises(CredentialsExpired) as caught:
            store.read()
        assert "--store" in str(caught.value)

    def test_an_empty_cookie_is_refused(self, store: CookieStore) -> None:
        with pytest.raises(CookieStoreError, match="empty"):
            store.write("   ")

    def test_a_stored_cookie_is_replaced_not_appended(self, store: CookieStore) -> None:
        store.write(COOKIE)
        store.write("newcookievalue")
        assert store.read() == "newcookievalue"

    def test_surrounding_whitespace_is_stripped(self, store: CookieStore) -> None:
        """Pasting from a browser's dev tools brings whitespace with it."""
        store.write(f"  {COOKIE}\n")
        assert store.read() == COOKIE

    def test_delete_removes_the_stored_cookie(self, store: CookieStore) -> None:
        store.write(COOKIE)
        store.delete()
        assert not store.exists()

    def test_a_missing_key_names_the_command_that_generates_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(KEY_ENV_VAR, raising=False)
        with pytest.raises(CookieStoreError) as caught:
            CookieStore.from_environment()
        assert "--generate-key" in str(caught.value)
        assert "It is the key, not the cookie" in str(caught.value)

    def test_an_invalid_key_is_rejected_before_it_is_used(self, tmp_path: Path) -> None:
        bad = CookieStore(path=tmp_path / "cookie.enc", key="not-a-fernet-key")
        with pytest.raises(CookieStoreError, match="not a valid Fernet key"):
            bad.write(COOKIE)

    def test_generated_keys_are_distinct(self) -> None:
        assert generate_key() != generate_key()


class TestSession:
    def test_the_cookie_is_set_on_the_fantrax_domain(self) -> None:
        session = build_session(COOKIE)
        assert session.cookies.get(COOKIE_NAME, domain=".fantrax.com") == COOKIE

    def test_the_session_identifies_itself(self) -> None:
        assert "hoops-gm" in build_session(COOKIE).headers["User-Agent"]


class FakeLeague:
    """Stands in for ``fantraxapi.League``, raising what it raises."""

    def __init__(self, exception: BaseException | None = None, result: Any = None) -> None:
        self.exception = exception
        self.result = result
        self.calls = 0

    def standings(self, **_kwargs: Any) -> Any:
        self.calls += 1
        if self.exception is not None:
            raise self.exception
        return self.result


def _named(name: str, base: type[Exception] = Exception) -> type[Exception]:
    """An exception class with a given name, to test name-based classification."""
    return type(name, (base,), {})


class TestErrorTranslation:
    def _client(self, league: FakeLeague, tmp_path: Path, **kwargs: Any) -> FantraxPrivateClient:
        # A real encrypted cookie store, so these exercise the actual path from
        # ciphertext on disk through to a session — everything except the
        # network, which is what the injected league stands in for.
        cookie_store = CookieStore(path=tmp_path / "cookie.enc", key=generate_key())
        cookie_store.write(COOKIE)
        return FantraxPrivateClient(
            "abc123",
            cookie_store=cookie_store,
            limiter=RateLimiter(0.0),
            retry_policy=RetryPolicy(attempts=2, base_delay_seconds=0.0, jitter=0.0),
            league_factory=lambda _league_id, _session: league,
            **kwargs,
        )

    def test_a_successful_read_passes_through(self, tmp_path: Path) -> None:
        league = FakeLeague(result=["standings"])
        assert self._client(league, tmp_path).standings() == ["standings"]

    def test_not_logged_in_becomes_expired_credentials_with_the_remedy(
        self, tmp_path: Path
    ) -> None:
        """The expected steady-state failure: session cookies expire. It gets a
        distinct class because the recovery is specific and documented."""
        league = FakeLeague(exception=_named("NotLoggedIn")("Not Logged in"))
        with pytest.raises(CredentialsExpired) as caught:
            self._client(league, tmp_path).standings()
        message = str(caught.value)
        assert "cookies --store" in message
        assert "docs/adapters/fantrax-private.md" in message

    def test_not_a_member_is_also_a_credentials_problem(self, tmp_path: Path) -> None:
        league = FakeLeague(exception=_named("NotMemberOfLeague")("nope"))
        with pytest.raises(CredentialsExpired):
            self._client(league, tmp_path).standings()

    def test_expired_credentials_are_not_retried(self, tmp_path: Path) -> None:
        """Repeating an authenticated request that just failed is how a session
        gets flagged."""
        league = FakeLeague(exception=_named("NotLoggedIn")("Not Logged in"))
        with pytest.raises(CredentialsExpired):
            self._client(league, tmp_path).standings()
        assert league.calls == 1

    def test_a_transport_failure_is_unavailable_and_is_retried(self, tmp_path: Path) -> None:
        league = FakeLeague(exception=_named("ReadTimeout")("slow"))
        with pytest.raises(SourceUnavailable):
            self._client(league, tmp_path).standings()
        assert league.calls == 2

    def test_an_unrecognised_failure_is_a_contract_error(self, tmp_path: Path) -> None:
        """`/fxpa/req` is undocumented internal infrastructure; anything we do
        not recognise might be it changing shape, and that must be loud."""
        league = FakeLeague(exception=_named("FantraxException")("something odd"))
        with pytest.raises(SourceContractError) as caught:
            self._client(league, tmp_path).standings()
        assert "undocumented internal" in str(caught.value)
        assert league.calls == 1

    def test_a_league_id_is_required(self) -> None:
        with pytest.raises(ValueError, match="league_id"):
            FantraxPrivateClient("")

    def test_a_missing_cookie_surfaces_before_any_request(self, tmp_path: Path) -> None:
        """The session is built lazily, so the first read is where a missing
        cookie is reported — with the command that fixes it."""
        league = FakeLeague(result=[])
        client = FantraxPrivateClient(
            "abc123",
            cookie_store=CookieStore(path=tmp_path / "absent.enc", key=generate_key()),
            limiter=RateLimiter(0.0),
            league_factory=lambda _league_id, _session: league,
        )
        with pytest.raises(CredentialsExpired):
            client.standings()
        assert league.calls == 0

    def test_resetting_the_session_re_reads_the_cookie(self, tmp_path: Path) -> None:
        """So a long-running process picks up a freshly stored cookie without a
        restart."""
        cookie_store = CookieStore(path=tmp_path / "cookie.enc", key=generate_key())
        cookie_store.write(COOKIE)
        built: list[int] = []

        def factory(_league_id: str, _session: Any) -> FakeLeague:
            built.append(1)
            return FakeLeague(result=[])

        client = FantraxPrivateClient(
            "abc123",
            cookie_store=cookie_store,
            limiter=RateLimiter(0.0),
            league_factory=factory,
        )
        client.standings()
        client.standings()
        assert built == [1], "the session is built once and reused"

        client.reset_session()
        client.standings()
        assert built == [1, 1], "and rebuilt after a reset"
