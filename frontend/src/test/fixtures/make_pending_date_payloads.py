"""Derive the doctored ``ScheduleLeagueV2`` payloads behind two recorded fixtures.

Why this file exists
--------------------

``schedule-grid-date-faults.recorded.json`` and
``schedule-grid-date-absent.recorded.json`` are recordings: real API responses,
captured from a real database, seeded by the real importer. But the *input* that
made the importer produce those four ``date_absence_reason`` values is not
something the NBA has ever sent — all six pending games in the live 2026-27
season carry reconcilable dates, so every non-empty reason fires zero times.

The inputs were therefore authored. They were authored once, by hand, and one of
the two was **overwritten before it was committed** — which is precisely the
failure a reviewer predicted when the fixtures landed without them: a recording
whose provenance is testimony, repairable only by hand-editing the JSON, which
silently converts it into a mock.

So the authored half is derived here instead of remembered. This script takes
the committed backend fixture as its base and applies the minimum edit that
reaches each reason, which makes the input->reason claim in the fixtures'
docstrings *checkable* rather than asserted:

    python make_pending_date_payloads.py --verify

re-derives both payloads and re-runs the importer's date classifier over them,
asserting the reasons the fixtures record. If the producer reorders
reconciliation and plausibility, a 1900 pair stops being ``implausible`` and
becomes ``irreconcilable`` — the frozen fixture would not notice, and this does.

The reasons, and the minimum edit that reaches each
---------------------------------------------------

``not_offered``    both time fields empty. The source published the game and no
                   date. The only cause that means *wait*.
``unreadable``     one field withheld, the other present. We cannot reconcile a
                   pair with one member, so we cannot read the date we were given.
``implausible``    a ``1900-01-01`` epoch pair. It reconciles perfectly -- the
                   offset is a real ``-05:00`` -- and names a date nowhere near
                   the season. Agreement is not validity.
``irreconcilable`` a pair one day apart. The source contradicting itself.

Only the two time fields are touched. Team blocks, ids, ``seriesText`` and every
resolved game are left exactly as the committed fixture has them, so anything the
capture shows outside those fields is the producer's.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[4]
FIXTURES = REPO / "backend/tests/fixtures"
#: The payload the demo seed actually imports -- 12 games, 10 resolved, 2
#: pending. It is the base on purpose: the recorded fixtures beside this script
#: are captures of the seeded demo database, so deriving from any other payload
#: would produce a different response and the "regenerates these fixtures"
#: claim would be false. There is a 24-game
#: ``..._pending_knockout.json`` next to it, and using it here was the first
#: version of this script -- ``--verify`` still passed, because it only checks
#: the two doctored games. Comparing the derived payload against a surviving
#: original is what caught it.
BASE = FIXTURES / "nba_scheduleleaguev2_2026_27.json"
#: Copied beside the derived payload so the output directory can be handed
#: straight to ``seed_schedule_grid --fixtures-dir``.
TEAMS = FIXTURES / "nba_static_teams.json"

# game id -> (gameDateTimeEst, gameDateTimeUTC), applied to the pending games in
# document order. Anything not named here keeps the base fixture's values.
VARIANTS: dict[str, dict[str, tuple[str, str]]] = {
    # Both faults, in one payload, so a single capture carries both.
    "faults": {
        # implausible: epoch placeholder pair, internally consistent (-05:00).
        "0022601201": ("1900-01-01T00:00:00Z", "1900-01-01T05:00:00Z"),
        # irreconcilable: the two fields name different days.
        "0022601202": ("2026-12-04T00:00:00Z", "2026-12-05T05:00:00Z"),
    },
    # Both absences, likewise paired.
    "absent": {
        # not_offered: the source committed to no date at all.
        "0022601201": ("", ""),
        # unreadable: one field withheld, so the pair cannot be reconciled.
        "0022601202": ("", "2026-12-04T05:00:00Z"),
    },
}

EXPECTED_REASONS = {
    "faults": {"0022601201": "implausible", "0022601202": "irreconcilable"},
    "absent": {"0022601201": "not_offered", "0022601202": "unreadable"},
}


def pending_games(payload: dict) -> list[dict]:
    return [
        game
        for day in payload["leagueSchedule"]["gameDates"]
        for game in day["games"]
        if game["homeTeam"]["teamId"] == 0
    ]


def derive(variant: str) -> dict:
    payload = json.loads(BASE.read_text(encoding="utf-8"))
    edits = VARIANTS[variant]
    touched: set[str] = set()
    for game in pending_games(payload):
        replacement = edits.get(game["gameId"])
        if replacement is None:
            continue
        game["gameDateTimeEst"], game["gameDateTimeUTC"] = replacement
        touched.add(game["gameId"])
    missing = set(edits) - touched
    if missing:
        raise SystemExit(
            f"{variant}: base fixture no longer contains pending games {sorted(missing)}. "
            "The ids moved; re-derive the edit rather than forcing the old ones."
        )
    return payload


def verify() -> int:
    """Re-run the producer's classifier over each derived payload."""
    sys.path.insert(0, str(REPO / "backend/src"))
    from hoops_gm.ingest.nba.schedule import _pending_game_date  # noqa: PLC0415

    failures = 0
    for variant, expected in EXPECTED_REASONS.items():
        payload = derive(variant)
        for game in pending_games(payload):
            want = expected.get(game["gameId"])
            if want is None:
                continue
            _, reason = _pending_game_date(game, game["gameId"], "2026-27")
            status = "ok " if reason == want else "FAIL"
            if reason != want:
                failures += 1
            print(f"{status} {variant:7} {game['gameId']}  want {want:14} got {reason!r}")
    if failures:
        print(
            f"\n{failures} classification(s) moved. The recorded fixtures assert the "
            "'want' column, so they are now claiming something the producer no "
            "longer does -- re-capture rather than editing the JSON."
        )
    else:
        print("\nAll input->reason claims hold against the in-tree producer.")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, help="directory to write payloads into")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="re-derive and re-classify, asserting the reasons the fixtures record",
    )
    args = parser.parse_args()

    if args.verify:
        return verify()
    if args.out is None:
        parser.error("pass --out to write payloads, or --verify to check them")

    args.out.mkdir(parents=True, exist_ok=True)
    for variant in VARIANTS:
        target = args.out / f"nba_scheduleleaguev2_2026_27_pending_{variant}.json"
        target.write_text(json.dumps(derive(variant), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {target}")
    (args.out / TEAMS.name).write_text(TEAMS.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"wrote {args.out / TEAMS.name} (unmodified, so --fixtures-dir works)")
    print(
        "\nTo re-capture a fixture, copy one variant over "
        f"{BASE.name} in a scratch directory alongside {TEAMS.name}, then:\n"
        "  python -m hoops_gm.dev.seed_schedule_grid --database-url sqlite:///./x.db "
        "--fixtures-dir <scratch>\n"
        "  DATABASE_URL=sqlite:///./x.db python -m hoops_gm\n"
        "  curl .../api/schedule/grid > <fixture>.recorded.json\n"
        "Compare against the committed fixture. Everything outside "
        "`pending_games` and `refreshed_at` should be identical; if it is not, "
        "the producer moved and that difference is the finding."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
