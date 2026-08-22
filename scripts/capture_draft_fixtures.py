"""Regenerate and drift-check the draft board's recorded fixtures.

## Why this exists

The draft board's tests are driven against payloads recorded from a real
backend. That is the right way to test a screen against a contract, and it has
one failure mode that is invisible from the frontend: **a recording goes stale
silently**. The backend changes its wording, every recorded test stays green,
and the screen shows text no test has ever seen.

That is not hypothetical. It happened on 2026-08-21. The base moved from
`5ec3d0f` to `ce4c603` carrying two message-correctness fixes, and two of the
six recorded refusals immediately held text the backend no longer produces --
including a re-wrap that asserted something untrue about the log. The frontend
suite was green throughout, because a recording cannot notice that it is old.

The original fixtures were captured by hand and no script was kept, so there was
nothing to re-run. Hence this file.

## The two modes

`--check` re-drives everything and compares against what is committed, reporting
**what it observed** rather than what it expected, and exits non-zero on drift.
This is the mode that turns a silent staleness into a loud one.

`--write` rewrites the refusal fixtures from the live backend.

Both seed a fresh SQLite database per case, so a success cannot contaminate the
next capture and a refusal cannot be mistaken for a rollback that leaked.

## Running it

There is no virtualenv in this checkout and `hoops_gm` otherwise resolves to a
stale namespace package in AppData. From `backend/`:

    $env:PYTHONPATH="$PWD\\src"; python ..\\scripts\\capture_draft_fixtures.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "frontend" / "src" / "test" / "fixtures"

AUCTION_DRAFT = 1
SNAKE_DRAFT = 2


def _client(tmp: Path, tag: str) -> Any:
    """A fresh seeded backend, one per case."""
    from fastapi.testclient import TestClient

    from hoops_gm.app import create_app
    from hoops_gm.core.config import Settings
    from hoops_gm.dev import seed_draft

    url = f"sqlite:///{tmp / (tag + '.db')}"
    seed_draft.main(["--database-url", url])
    settings = Settings(database_url=url, environment="test")
    return TestClient(create_app(settings), base_url="http://127.0.0.1:8000")


def _refusal(client: Any, draft_id: int, body: dict[str, Any]) -> dict[str, Any]:
    resp = client.post(f"/api/v1/drafts/{draft_id}/events", json=body)
    if resp.status_code < 400:
        raise AssertionError(
            f"expected a refusal, observed {resp.status_code}. "
            f"This case no longer refuses, so the fixture it produces would be a lie."
        )
    payload = resp.json()
    return {"status": resp.status_code, "body": payload}


def _open_a_lot(client: Any, participant_id: int, label: str) -> None:
    resp = client.post(
        f"/api/v1/drafts/{AUCTION_DRAFT}/events",
        json={
            "event_type": "nomination",
            "participant_id": participant_id,
            "player_label": label,
            "amount": "1.00",
        },
    )
    if resp.status_code != 201:
        raise AssertionError(f"could not open a lot: {resp.status_code} {resp.text}")


def capture_refusals(tmp: Path) -> dict[str, dict[str, Any]]:
    """Drive each refusal the board renders, in its own database."""
    out: dict[str, dict[str, Any]] = {}

    # A void of an event that is neither the tail nor safely replayable. The
    # message names the *later* sequence that stops holding, which is the whole
    # point of the "try to void" affordance.
    with _client(tmp, "void-non-tail") as c:
        out["void-non-tail"] = _refusal(
            c, AUCTION_DRAFT, {"event_type": "void", "supersedes_sequence": 5}
        )

    # Void hygiene: a void is not itself undoable. Before ce4c603 this arrived
    # wrapped in a sentence about a later sequence that had nothing to do with
    # it; the wrap was dead code asserting a false fact.
    with _client(tmp, "void-a-void") as c:
        events = c.get(f"/api/v1/drafts/{AUCTION_DRAFT}/events").json()["events"]
        voids = [e["sequence"] for e in events if e["event_type"] == "void"]
        if not voids:
            raise AssertionError(
                "the seed contains no void, so there is nothing to void-a-void. "
                "Observed event types: " + ", ".join(sorted({e["event_type"] for e in events}))
            )
        out["void-a-void"] = _refusal(
            c, AUCTION_DRAFT, {"event_type": "void", "supersedes_sequence": voids[0]}
        )

    # The one refusal the screen must treat as retryable rather than fatal.
    with _client(tmp, "sequence-conflict") as c:
        state = c.get(f"/api/v1/drafts/{AUCTION_DRAFT}").json()
        seat = state["participants"][0]["id"]
        out["sequence-conflict"] = _refusal(
            c,
            AUCTION_DRAFT,
            {
                "event_type": "nomination",
                "participant_id": seat,
                "player_label": "Stale Writer",
                "amount": "1.00",
                "expected_last_sequence": 2,
            },
        )

    with _client(tmp, "bid-not-increasing") as c:
        state = c.get(f"/api/v1/drafts/{AUCTION_DRAFT}").json()
        seat = state["participants"][0]["id"]
        other = state["participants"][1]["id"]
        _open_a_lot(c, seat, "Fixture Nominee")
        raised = c.post(
            f"/api/v1/drafts/{AUCTION_DRAFT}/events",
            json={"event_type": "bid", "participant_id": other, "amount": "150.00"},
        )
        if raised.status_code != 201:
            raise AssertionError(f"could not raise a bid: {raised.status_code} {raised.text}")
        out["bid-not-increasing"] = _refusal(
            c,
            AUCTION_DRAFT,
            {"event_type": "bid", "participant_id": seat, "amount": "100.00"},
        )

    with _client(tmp, "budget-exceeded") as c:
        state = c.get(f"/api/v1/drafts/{AUCTION_DRAFT}").json()
        seat = state["participants"][0]["id"]
        _open_a_lot(c, seat, "Unaffordable Nominee")
        out["budget-exceeded"] = _refusal(
            c,
            AUCTION_DRAFT,
            {"event_type": "sale", "participant_id": seat, "amount": "999"},
        )

    with _client(tmp, "unknown-participant") as c:
        state = c.get(f"/api/v1/drafts/{AUCTION_DRAFT}").json()
        _open_a_lot(c, state["participants"][0]["id"], "Orphan Lot")
        out["unknown-participant"] = _refusal(
            c,
            AUCTION_DRAFT,
            {"event_type": "sale", "participant_id": 999, "amount": "5.00"},
        )

    if len(out) != 6:
        raise AssertionError(f"captured {len(out)} refusals, expected 6")
    return out


def _normalise(payload: Any) -> Any:
    """Drop the fields that legitimately move between captures."""
    if isinstance(payload, dict):
        return {k: _normalise(v) for k, v in payload.items() if k != "request_id"}
    if isinstance(payload, list):
        return [_normalise(v) for v in payload]
    return payload


def _read(name: str) -> Any:
    path = FIXTURES / f"{name}.recorded.json"
    if not path.exists():
        raise AssertionError(f"fixture {path} is missing, so there is nothing to compare against")
    return json.loads(path.read_text(encoding="utf-8"))


def check(tmp: Path) -> int:
    """Compare every recorded fixture against a freshly driven backend."""
    drift: list[str] = []
    checked = 0

    live_refusals = capture_refusals(tmp)
    recorded_refusals = _read("draft-refusals")
    for name, live in live_refusals.items():
        checked += 1
        if name not in recorded_refusals:
            drift.append(f"{name}: not in the committed fixture at all")
            continue
        was = _normalise(recorded_refusals[name])
        now = _normalise(live)
        if was != now:
            drift.append(
                f"{name}:\n"
                f"    committed status {was['status']} code {was['body'].get('error')}\n"
                f"      observed status {now['status']} code {now['body'].get('error')}\n"
                f"    committed detail: {was['body'].get('detail')}\n"
                f"      observed detail: {now['body'].get('detail')}"
            )

    # The state and event payloads carry no prose, so they drift for a different
    # reason: a schema or seed change. Compared on shape, not on every value.
    with _client(tmp, "shapes") as c:
        for name, url in (
            ("draft-auction-state", f"/api/v1/drafts/{AUCTION_DRAFT}"),
            ("draft-snake-state", f"/api/v1/drafts/{SNAKE_DRAFT}"),
            ("draft-list", "/api/v1/drafts"),
        ):
            checked += 1
            live = c.get(url).json()
            recorded = _read(name)
            missing = sorted(set(recorded) - set(live))
            added = sorted(set(live) - set(recorded))
            if missing or added:
                drift.append(f"{name}: keys gone {missing}, keys new {added}")

    if checked == 0:
        raise AssertionError("checked nothing - a clean report here would be meaningless")

    print(f"checked {checked} recorded payloads against a freshly seeded backend")
    if drift:
        print(f"\nDRIFT in {len(drift)} of {checked}:\n")
        for item in drift:
            print(f"  {item}\n")
        return 1
    print("no drift")
    return 0


def write(tmp: Path) -> int:
    refusals = capture_refusals(tmp)
    path = FIXTURES / "draft-refusals.recorded.json"
    path.write_text(json.dumps(refusals, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(refusals)} refusals to {path.relative_to(REPO_ROOT)}:")
    for name, value in refusals.items():
        print(f"  {name}: {value['status']} {value['body'].get('error')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report drift, change nothing")
    parser.add_argument("--write", action="store_true", help="rewrite the refusal fixtures")
    args = parser.parse_args(argv)
    if args.check == args.write:
        parser.error("pass exactly one of --check or --write")

    action: Callable[[Path], int] = check if args.check else write
    # ignore_cleanup_errors: SQLite keeps a handle open on Windows after close.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        return action(Path(raw))


if __name__ == "__main__":
    sys.exit(main())
