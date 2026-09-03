"""Offline Adapter-gate coverage for official NBA transaction archives."""

from __future__ import annotations

import copy
import gzip
import hashlib
import http.client
import io
import json
import urllib.error
from datetime import date, timedelta
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from hoops_gm.ingest.errors import SourceContractError, SourceRejected
from hoops_gm.ingest.nba_transactions import (
    G_LEAGUE_TRANSACTION_FIELDS,
    G_LEAGUE_TRANSACTIONS_ENDPOINT,
    G_LEAGUE_TRANSACTIONS_URL,
    G_LEAGUE_TYPE_DESCRIPTIONS,
    NBA_PLAYER_MOVEMENT_ENDPOINT,
    NBA_PLAYER_MOVEMENT_FIELDS,
    NBA_PLAYER_MOVEMENT_TYPES,
    NBA_PLAYER_MOVEMENT_URL,
    SOURCE,
    NbaOfficialTransactionsClient,
    parse_g_league_transactions,
    parse_nba_player_movements,
)
from hoops_gm.ingest.nba_transactions.client import _default_nba_transport
from hoops_gm.ingest.rawstore import RawPayloadStore
from hoops_gm.ingest.retry import RetryPolicy
from hoops_gm.ingest.throttle import RateLimiter

pytestmark = pytest.mark.adapter_contract

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NBA_FIXTURE_SHA256 = "a5597174e2ac7b07d2654f7e875225a42c01c2df445d2085c585508345ae63d4"
G_LEAGUE_FIXTURE_SHA256 = "ce21d2a2ae0b76944952364b0122481c10115b177c28ea59055b68d5bbb38ac8"


def load_gzip_bytes(name: str) -> bytes:
    with gzip.open(FIXTURES / name, "rb") as handle:
        return handle.read()


def load_gzip_json(name: str) -> Any:
    return json.loads(load_gzip_bytes(name).decode("utf-8"))


@pytest.fixture(scope="module")
def nba_payload() -> dict[str, Any]:
    payload = load_gzip_json("nba_player_movement.json.gz")
    assert isinstance(payload, dict)
    return payload


@pytest.fixture(scope="module")
def g_league_payload() -> list[dict[str, Any]]:
    payload = load_gzip_json("nba_gleague_transactions.json.gz")
    assert isinstance(payload, list)
    return payload


class TestNbaPlayerMovementContract:
    def test_fixture_preserves_the_exact_full_response_body(self) -> None:
        body = load_gzip_bytes("nba_player_movement.json.gz")
        assert len(body) == 4_135_059
        assert hashlib.sha256(body).hexdigest() == NBA_FIXTURE_SHA256

    def test_complete_archive_matches_the_measured_contract(
        self, nba_payload: dict[str, Any]
    ) -> None:
        records = parse_nba_player_movements(nba_payload)

        assert len(records) == 9777
        assert {record.transaction_type for record in records} == NBA_PLAYER_MOVEMENT_TYPES
        assert min(record.transaction_date for record in records) == date(2015, 7, 1)
        assert max(record.transaction_date for record in records) == date(2026, 9, 2)

    def test_consideration_only_rows_remain_explicit(self, nba_payload: dict[str, Any]) -> None:
        records = parse_nba_player_movements(nba_payload)
        non_player = [record for record in records if record.nba_player_id is None]

        assert len(non_player) == 518
        assert all(record.player_slug is None for record in non_player)
        assert all(record.transaction_type == "Trade" for record in non_player)

    def test_known_silent_windows_have_dated_roster_movements(
        self, nba_payload: dict[str, Any]
    ) -> None:
        records = parse_nba_player_movements(nba_payload)
        relevant = {
            (
                record.nba_player_id,
                record.transaction_date,
                record.transaction_type,
                record.nba_team_id,
                record.related_team_id,
            )
            for record in records
            if record.nba_player_id in {201144, 1630164, 1643047}
        }

        assert {
            (201144, date(2026, 2, 3), "Trade", 1610612741, 1610612750),
            (201144, date(2026, 2, 4), "Trade", 1610612766, 1610612741),
            (201144, date(2026, 2, 5), "Waive", 1610612766, None),
            (201144, date(2026, 2, 17), "Signing", 1610612750, None),
            (1630164, date(2025, 10, 28), "Waive", 1610612754, None),
            (1630164, date(2025, 12, 20), "Signing", 1610612754, None),
            (1643047, date(2025, 11, 17), "Waive", 1610612756, None),
            (1643047, date(2026, 3, 2), "Signing", 1610612756, None),
        } <= relevant

    def test_row_fields_are_exact_not_best_effort(self, nba_payload: dict[str, Any]) -> None:
        row = nba_payload["NBA_Player_Movement"]["rows"][0]
        assert set(row) == NBA_PLAYER_MOVEMENT_FIELDS

        missing = copy.deepcopy(nba_payload)
        del missing["NBA_Player_Movement"]["rows"][0]["TEAM_ID"]
        with pytest.raises(SourceContractError, match=r"missing=.*TEAM_ID"):
            parse_nba_player_movements(missing)

        added = copy.deepcopy(nba_payload)
        added["NBA_Player_Movement"]["rows"][0]["new_field"] = "drift"
        with pytest.raises(SourceContractError, match=r"unexpected=.*new_field"):
            parse_nba_player_movements(added)

    def test_unknown_type_is_not_silently_admitted(self, nba_payload: dict[str, Any]) -> None:
        mutated = copy.deepcopy(nba_payload)
        mutated["NBA_Player_Movement"]["rows"][0]["Transaction_Type"] = "Suspension"
        with pytest.raises(SourceContractError, match="unknown Transaction_Type"):
            parse_nba_player_movements(mutated)

    def test_self_described_column_contract_is_pinned(self, nba_payload: dict[str, Any]) -> None:
        mutated = copy.deepcopy(nba_payload)
        mutated["NBA_Player_Movement"]["columns"][1]["DataType"] = "String"
        with pytest.raises(SourceContractError, match="column contract changed"):
            parse_nba_player_movements(mutated)

    def test_non_integral_identifier_is_rejected(self, nba_payload: dict[str, Any]) -> None:
        mutated = copy.deepcopy(nba_payload)
        mutated["NBA_Player_Movement"]["rows"][0]["PLAYER_ID"] = 1.5
        with pytest.raises(SourceContractError, match="PLAYER_ID"):
            parse_nba_player_movements(mutated)

    def test_consideration_identity_pair_cannot_be_half_missing(
        self, nba_payload: dict[str, Any]
    ) -> None:
        mutated = copy.deepcopy(nba_payload)
        row = mutated["NBA_Player_Movement"]["rows"][0]
        row["PLAYER_ID"] = 0.0
        row["PLAYER_SLUG"] = "not-blank"
        with pytest.raises(SourceContractError, match="pair PLAYER_ID 0"):
            parse_nba_player_movements(mutated)

    def test_date_must_retain_the_observed_midnight_shape(
        self, nba_payload: dict[str, Any]
    ) -> None:
        mutated = copy.deepcopy(nba_payload)
        mutated["NBA_Player_Movement"]["rows"][0]["TRANSACTION_DATE"] = "2026-09-02"
        with pytest.raises(SourceContractError, match="TRANSACTION_DATE"):
            parse_nba_player_movements(mutated)

        unpadded = copy.deepcopy(nba_payload)
        unpadded["NBA_Player_Movement"]["rows"][0]["TRANSACTION_DATE"] = "2026-9-2T00:00:00"
        with pytest.raises(SourceContractError, match="TRANSACTION_DATE"):
            parse_nba_player_movements(unpadded)


class TestGLeagueTransactionContract:
    def test_fixture_preserves_the_exact_full_response_body(self) -> None:
        body = load_gzip_bytes("nba_gleague_transactions.json.gz")
        assert len(body) == 3_701_195
        assert hashlib.sha256(body).hexdigest() == G_LEAGUE_FIXTURE_SHA256

    def test_complete_archive_matches_the_measured_contract(
        self, g_league_payload: list[dict[str, Any]]
    ) -> None:
        records = parse_g_league_transactions(g_league_payload)

        assert len(records) == 14184
        assert {record.transaction_type for record in records} == set(G_LEAGUE_TYPE_DESCRIPTIONS)
        assert min(record.transaction_date for record in records) == date(2021, 8, 3)
        assert max(record.transaction_date for record in records) == date(2026, 8, 31)

    def test_assignment_recall_and_call_up_rows_are_preserved(
        self, g_league_payload: list[dict[str, Any]]
    ) -> None:
        records = parse_g_league_transactions(g_league_payload)
        relevant = {
            (
                record.nba_player_id,
                record.transaction_date,
                record.transaction_description,
                record.g_league_team_id,
                record.related_team_id,
            )
            for record in records
            if record.nba_player_id in {1630164, 1643047}
        }

        assert {
            (1630164, date(2022, 11, 15), "Assigned", 1612709902, None),
            (1630164, date(2022, 12, 15), "Recalled", 1612709902, 1610612744),
            (1643047, date(2025, 11, 20), "Acquired", 1612709934, None),
            (1643047, date(2026, 3, 2), "NBA Call-Up", 1612709934, 1610612756),
        } <= relevant

    def test_row_fields_are_exact_not_best_effort(
        self, g_league_payload: list[dict[str, Any]]
    ) -> None:
        assert set(g_league_payload[0]) == G_LEAGUE_TRANSACTION_FIELDS

        missing = copy.deepcopy(g_league_payload)
        del missing[0]["PLAYER_ID"]
        with pytest.raises(SourceContractError, match=r"missing=.*PLAYER_ID"):
            parse_g_league_transactions(missing)

        added = copy.deepcopy(g_league_payload)
        added[0]["new_field"] = "drift"
        with pytest.raises(SourceContractError, match=r"unexpected=.*new_field"):
            parse_g_league_transactions(added)

    def test_unknown_type_description_pair_is_rejected(
        self, g_league_payload: list[dict[str, Any]]
    ) -> None:
        mutated = copy.deepcopy(g_league_payload)
        mutated[0]["TRANSACTION_DESCRIPTION"] = "Suspended"
        with pytest.raises(SourceContractError, match="unknown type/description pair"):
            parse_g_league_transactions(mutated)

    def test_team_identity_pair_cannot_be_half_missing(
        self, g_league_payload: list[dict[str, Any]]
    ) -> None:
        mutated = copy.deepcopy(g_league_payload)
        mutated[0]["TEAM_ID"] = 0
        mutated[0]["TEAM_SLUG"] = "not-blank"
        with pytest.raises(SourceContractError, match="pair TEAM_ID 0"):
            parse_g_league_transactions(mutated)

    def test_date_must_retain_the_observed_date_shape(
        self, g_league_payload: list[dict[str, Any]]
    ) -> None:
        mutated = copy.deepcopy(g_league_payload)
        mutated[0]["TRANSACTION_DATE"] = "08/31/2026"
        with pytest.raises(SourceContractError, match="TRANSACTION_DATE"):
            parse_g_league_transactions(mutated)

        unpadded = copy.deepcopy(g_league_payload)
        unpadded[0]["TRANSACTION_DATE"] = "2026-8-3"
        with pytest.raises(SourceContractError, match="TRANSACTION_DATE"):
            parse_g_league_transactions(unpadded)


def test_documented_protocol_window_source_counts(
    nba_payload: dict[str, Any], g_league_payload: list[dict[str, Any]]
) -> None:
    nba = parse_nba_player_movements(nba_payload)
    g_league = parse_g_league_transactions(g_league_payload)
    windows = {
        "2022-23": (date(2022, 10, 18), date(2023, 4, 9)),
        "2023-24": (date(2023, 10, 24), date(2024, 4, 14)),
        "2024-25": (date(2024, 10, 22), date(2025, 4, 13)),
        "2025-26": (date(2025, 10, 21), date(2026, 4, 12)),
    }
    expected = {
        "2022-23": (296, 267, 2472, 552, 552, 58),
        "2023-24": (357, 328, 2612, 583, 581, 83),
        "2024-25": (352, 311, 2427, 481, 480, 82),
        "2025-26": (358, 333, 2518, 440, 440, 88),
    }

    actual: dict[str, tuple[int, int, int, int, int, int]] = {}
    for season, (start, end) in windows.items():
        nba_rows = [record for record in nba if start <= record.transaction_date <= end]
        g_rows = [record for record in g_league if start <= record.transaction_date <= end]
        actual[season] = (
            len(nba_rows),
            sum(record.nba_player_id is not None for record in nba_rows),
            len(g_rows),
            sum(record.transaction_description == "Assigned" for record in g_rows),
            sum(record.transaction_description == "Recalled" for record in g_rows),
            sum(record.transaction_description == "NBA Call-Up" for record in g_rows),
        )

    assert actual == expected


class FakeRequestsResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.content = body
        self.status_code = status
        self.headers = {"Content-Type": "application/json"}
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeNbaSession:
    def __init__(self, *responses: FakeRequestsResponse) -> None:
        self.responses = list(responses)
        self.calls = 0

    def get(self, url: str, **kwargs: Any) -> FakeRequestsResponse:
        del url, kwargs
        response = self.responses[self.calls]
        self.calls += 1
        return response


class FakeUrlResponse:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self) -> FakeUrlResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeGLeagueOpener:
    def __init__(self, *outcomes: Exception | FakeUrlResponse) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, request: Any, **kwargs: Any) -> FakeUrlResponse:
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


class TestOfficialTransactionTransport:
    def test_malformed_body_is_captured_without_poisoning_success_cache(
        self, tmp_path: Path
    ) -> None:
        body = b"<html>upstream error under HTTP 200</html>"
        valid = b'{"recovered":true}'
        session = FakeNbaSession(FakeRequestsResponse(body), FakeRequestsResponse(valid))
        store = RawPayloadStore(tmp_path)
        client = NbaOfficialTransactionsClient(
            store=store,
            limiter=RateLimiter(0),
            nba_session=session,
            nba_headers={},
        )

        with pytest.raises(SourceContractError, match="not UTF-8 JSON"):
            client.fetch_json(NBA_PLAYER_MOVEMENT_ENDPOINT, max_age=timedelta(0))

        captures = store.history(
            source=SOURCE,
            endpoint=f"{NBA_PLAYER_MOVEMENT_ENDPOINT}.contract_error",
            params={
                "url": ("https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json")
            },
        )
        assert len(captures) == 1
        assert captures[0].read_bytes() == body
        assert client.fetch_json(NBA_PLAYER_MOVEMENT_ENDPOINT) == {"recovered": True}
        assert client.fetch_json(NBA_PLAYER_MOVEMENT_ENDPOINT) == {"recovered": True}
        assert session.calls == 2

    def test_fresh_capture_prevents_a_second_request(self, tmp_path: Path) -> None:
        body = b'{"NBA_Player_Movement":{"rows":[]}}'
        session = FakeNbaSession(FakeRequestsResponse(body))
        client = NbaOfficialTransactionsClient(
            store=RawPayloadStore(tmp_path),
            limiter=RateLimiter(0),
            nba_session=session,
            nba_headers={},
        )

        assert client.fetch_json(NBA_PLAYER_MOVEMENT_ENDPOINT) == {
            "NBA_Player_Movement": {"rows": []}
        }
        assert client.fetch_json(NBA_PLAYER_MOVEMENT_ENDPOINT) == {
            "NBA_Player_Movement": {"rows": []}
        }
        assert session.calls == 1

    def test_non_retryable_http_refusal_is_explicit(self, tmp_path: Path) -> None:
        store = RawPayloadStore(tmp_path)
        client = NbaOfficialTransactionsClient(
            store=store,
            limiter=RateLimiter(0),
            nba_session=FakeNbaSession(FakeRequestsResponse(b"forbidden", status=403)),
            nba_headers={},
        )

        with pytest.raises(SourceRejected) as caught:
            client.fetch_json(NBA_PLAYER_MOVEMENT_ENDPOINT, max_age=timedelta(0))
        assert caught.value.status_code == 403
        captures = store.history(
            source=SOURCE,
            endpoint=f"{NBA_PLAYER_MOVEMENT_ENDPOINT}.http_error",
            params={"url": NBA_PLAYER_MOVEMENT_URL},
        )
        assert len(captures) == 1
        assert captures[0].read_bytes() == b"forbidden"

    def test_any_5xx_response_is_retried(self) -> None:
        session = FakeNbaSession(
            FakeRequestsResponse(b"not implemented", status=501),
            FakeRequestsResponse(b"{}"),
        )
        client = NbaOfficialTransactionsClient(
            limiter=RateLimiter(0),
            retry_policy=RetryPolicy(attempts=2, base_delay_seconds=0, jitter=0),
            nba_session=session,
            nba_headers={},
        )

        assert client.fetch_json(NBA_PLAYER_MOVEMENT_ENDPOINT, max_age=timedelta(0)) == {}
        assert session.calls == 2

    def test_default_nba_headers_do_not_advertise_unsupported_brotli(self) -> None:
        _session, headers = _default_nba_transport()

        assert headers["Accept-Encoding"] == "gzip, deflate"

    def test_truncated_g_league_body_is_captured_and_retried(self, tmp_path: Path) -> None:
        partial = b'{"partial"'
        opener = FakeGLeagueOpener(
            http.client.IncompleteRead(partial, 100),
            FakeUrlResponse(b"[]"),
        )
        store = RawPayloadStore(tmp_path)
        client = NbaOfficialTransactionsClient(
            store=store,
            limiter=RateLimiter(0),
            retry_policy=RetryPolicy(attempts=2, base_delay_seconds=0, jitter=0),
            nba_session=FakeNbaSession(),
            nba_headers={},
            g_league_opener=opener,
        )

        assert client.fetch_json(G_LEAGUE_TRANSACTIONS_ENDPOINT, max_age=timedelta(0)) == []
        assert opener.calls == 2
        captures = store.history(
            source=SOURCE,
            endpoint=f"{G_LEAGUE_TRANSACTIONS_ENDPOINT}.incomplete_read",
            params={"url": G_LEAGUE_TRANSACTIONS_URL},
        )
        assert len(captures) == 1
        assert captures[0].read_bytes() == partial

    def test_truncated_5xx_body_is_captured_and_retried(self, tmp_path: Path) -> None:
        partial = b'{"upstream"'
        headers = Message()
        headers["Content-Type"] = "application/json"
        error = urllib.error.HTTPError(
            G_LEAGUE_TRANSACTIONS_URL,
            503,
            "Service Unavailable",
            headers,
            IncompleteErrorBody(partial),
        )
        opener = FakeGLeagueOpener(error, FakeUrlResponse(b"[]"))
        store = RawPayloadStore(tmp_path)
        client = NbaOfficialTransactionsClient(
            store=store,
            limiter=RateLimiter(0),
            retry_policy=RetryPolicy(attempts=2, base_delay_seconds=0, jitter=0),
            nba_session=FakeNbaSession(),
            nba_headers={},
            g_league_opener=opener,
        )

        assert client.fetch_json(G_LEAGUE_TRANSACTIONS_ENDPOINT, max_age=timedelta(0)) == []
        assert opener.calls == 2
        captures = store.history(
            source=SOURCE,
            endpoint=f"{G_LEAGUE_TRANSACTIONS_ENDPOINT}.incomplete_http_error",
            params={"url": G_LEAGUE_TRANSACTIONS_URL},
        )
        assert len(captures) == 1
        assert captures[0].read_bytes() == partial
