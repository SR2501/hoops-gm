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

re-derives all three payloads, asserts each derived pending set matches its
fixture's ``pending_game_ids``, re-runs the importer's date classifier against
the reasons **read out of the fixtures themselves**, and recomputes all 630
per-period per-team count rows from the derived payload to compare against the
recorded ones. If the producer reorders reconciliation and plausibility, a 1900
pair stops being ``implausible`` — the frozen fixture would not notice, and this
does. If somebody hand-edits a reason in the JSON, that fails here too, which is
the conversion-into-a-mock this whole file exists to prevent.

The counts comparison is there because two earlier versions of this check were
**green while pointed at the wrong artifact**. It pinned only the pending block,
so a resolved game was free to move between scoring periods — a within-DST shift
that reconciles cleanly, which is exactly what a re-capture would produce — while
this printed success. Two of twelve games were checked and the success line was
read as covering the response.

It does **not** claim to reproduce the lost payload byte for byte. A different
input reaching the same response would be indistinguishable, and identity is not
what the fixtures need: they need *some derivable input* producing those reasons
and that response. The two doctored variants are also not equally anchored —
``absent`` was checked against a surviving original, ``faults`` never could be,
because its original was already gone. Both regenerate the committed response to
a single ``refreshed_at`` leaf.

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
import os
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
#: version of this script -- ``--verify`` still passed, because it only checked
#: the two doctored games, and that payload contains the same two ids. What
#: caught it was a comparison against a payload that no longer exists, so
#: ``verify`` now asserts the derived pending set equals the fixture's
#: ``pending_game_ids`` instead: the same substitution fails loudly and needs no
#: artifact anybody has to have kept.
BASE = FIXTURES / "nba_scheduleleaguev2_2026_27.json"
#: Copied beside the derived payload so the output directory can be handed
#: straight to ``seed_schedule_grid --fixtures-dir``.
TEAMS = FIXTURES / "nba_static_teams.json"

# game id -> (gameDateTimeEst, gameDateTimeUTC), applied to the pending games in
# document order. Anything not named here keeps the base fixture's values.
VARIANTS: dict[str, dict[str, tuple[str, str]]] = {
    # No edits: the committed base, captured as `schedule-grid-current`. It is a
    # variant so the verifier covers it; ``--out`` writes it too, which makes the
    # undoctored payload seedable by the same recipe as the other two.
    "current": {},
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

#: The recorded fixture each variant produced. Expectations are read out of
#: these rather than kept beside them: ``EXPECTED_REASONS`` used to be a
#: hardcoded dict, which made ``--verify`` compare the classifier against a
#: hand-maintained third copy of data the fixtures already hold. It could then
#: report "all claims hold" while somebody had hand-edited a reason in the JSON
#: -- the precise conversion-of-recording-into-mock this file exists to prevent,
#: inside the check written to prevent it.
RECORDED = {
    # Undoctored: the base as committed, which every other comparison is
    # anchored on. Included so `--verify` pins the payload the other two are
    # edits *of*, and so the loop below covers every recording in this
    # directory rather than only the ones with edits.
    "current": pathlib.Path(__file__).parent / "schedule-grid-current.recorded.json",
    "faults": pathlib.Path(__file__).parent / "schedule-grid-date-faults.recorded.json",
    "absent": pathlib.Path(__file__).parent / "schedule-grid-date-absent.recorded.json",
}


def recorded_expectations(variant: str) -> tuple[list[str], dict[str, str]]:
    """The pending ids and reasons the committed fixture actually records."""
    schedule = json.loads(RECORDED[variant].read_text(encoding="utf-8"))["lineage"]["schedule"]
    reasons = {
        game["nba_game_id"]: game["date_absence_reason"] for game in schedule["pending_games"]
    }
    return list(schedule["pending_game_ids"]), reasons


def recorded_counts(variant: str) -> tuple[dict, list[dict], list[dict]]:
    fixture = json.loads(RECORDED[variant].read_text(encoding="utf-8"))
    return fixture, fixture["periods"], fixture["counts"]


def derived_counts(payload: dict, periods: list[dict], teams: list[dict], season: str) -> dict:
    """Per-period per-team game counts implied by the derived payload.

    Recomputed with the producer's own parser rather than by re-reading dates
    out of the raw JSON, so a change to how the producer resolves a date shows
    up here instead of being reproduced by a second implementation of it.
    """
    sys.path.insert(0, str(REPO / "backend/src"))
    from hoops_gm.ingest.nba.schedule import parse_schedule

    by_nba_id = {team["nba_team_id"]: team["team_id"] for team in teams}
    counts: dict[tuple[int, int], int] = {}
    for record in parse_schedule(payload, season=season).games:
        day = record.game.game_date.isoformat()
        period = next(
            (p for p in periods if p["start_date"] <= day <= p["end_date"]),
            None,
        )
        if period is None:
            continue
        for nba_team_id in (record.home_nba_team_id, record.away_nba_team_id):
            key = (period["period_number"], by_nba_id[nba_team_id])
            counts[key] = counts.get(key, 0) + 1
    return counts


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
    """Check the derived payloads against the fixtures they are said to produce.

    Two claims, both previously unenforced:

    *The base is the right one.* Deriving from ``..._pending_knockout.json``
    instead of the payload the demo seed imports produced a generator that could
    not regenerate the fixtures, and the earlier version of this function
    **printed success anyway**, because it only classified the two games it
    doctors and both classified correctly. That payload contains the same two
    ids, so an id-membership check does not catch it -- the derived pending set
    must equal the fixture's ``pending_game_ids`` exactly.

    *The reasons are the recorded ones.* Read from the fixture rather than from a
    dict kept beside it, so a hand-edit to the JSON fails here instead of being
    blessed by the check written to prevent hand-edits.
    """
    sys.path.insert(0, str(REPO / "backend/src"))
    from hoops_gm.ingest.nba.schedule import _pending_game_date

    if set(RECORDED) != set(VARIANTS):
        raise SystemExit(
            f"every recording must have a variant and vice versa; "
            f"recordings-only {sorted(set(RECORDED) - set(VARIANTS))}, "
            f"variants-only {sorted(set(VARIANTS) - set(RECORDED))}. "
            "A recording with no variant is skipped silently, which is the "
            "defect this function keeps being caught by."
        )

    failures = 0
    for variant in VARIANTS:
        recorded_ids, expected = recorded_expectations(variant)
        payload = derive(variant)
        derived_ids = [game["gameId"] for game in pending_games(payload)]

        if derived_ids != recorded_ids:
            failures += 1
            print(
                f"FAIL {variant:7} pending set differs from the fixture it claims to "
                f"produce:\n       derived  {derived_ids}\n       recorded {recorded_ids}\n"
                f"       {BASE.name} is not the payload this fixture was captured from."
            )
            continue

        for game in pending_games(payload):
            want = expected[game["gameId"]]
            _, reason = _pending_game_date(game, game["gameId"], "2026-27")
            status = "ok " if reason == want else "FAIL"
            if reason != want:
                failures += 1
            print(f"{status} {variant:7} {game['gameId']}  recorded {want:14} got {reason!r}")

        # The resolved ten twelfths. Pinning only the pending block left a
        # resolved game free to move between scoring periods -- a within-DST
        # shift that reconciles cleanly -- while this printed success, which is
        # the third time this function has been green about an artifact it was
        # not looking at. The counts are what the screen renders, so they are
        # what gets compared.
        fixture, periods, counts = recorded_counts(variant)
        derived = derived_counts(payload, periods, fixture["teams"], fixture["season"])
        mismatches = [
            row
            for row in counts
            if derived.get((row["period_number"], row["team_id"]), 0) != row["games"]
        ]
        if mismatches:
            failures += 1
            head = mismatches[0]
            print(
                f"FAIL {variant:7} {len(mismatches)} of {len(counts)} count rows differ from "
                f"the fixture; first is period {head['period_number']} team {head['team_id']}: "
                f"recorded {head['games']}, derived "
                f"{derived.get((head['period_number'], head['team_id']), 0)}."
            )
        else:
            print(f"ok  {variant:7} all {len(counts)} recorded count rows reproduced")

    if failures:
        print(
            f"\n{failures} check(s) failed. Either the producer's classification moved, "
            "in which case re-capture rather than editing the JSON, or a fixture was "
            "hand-edited, in which case it has stopped being a recording."
        )
    else:
        print("\nEvery recorded reason and count row is reproduced by the in-tree producer.")
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
        # Each variant gets its own directory holding the payload under the name
        # the seed reads, so the directory is handed straight to
        # `--fixtures-dir` with no copy step. The earlier version wrote both
        # variants side by side under distinguishing names and told the reader to
        # copy one over the base filename -- which is the exact operation that
        # destroyed the original faults payload. A file whose purpose is removing
        # a hand-step should not document one.
        target_dir = args.out / variant
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / BASE.name
        target.write_text(json.dumps(derive(variant), indent=2) + "\n", encoding="utf-8")
        (target_dir / TEAMS.name).write_text(TEAMS.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"wrote {target_dir}{os.sep}  ({BASE.name} + {TEAMS.name})")
    print(
        "\nEach directory is directly seedable. To re-capture a fixture:\n"
        "  python -m hoops_gm.dev.seed_schedule_grid --database-url sqlite:///./x.db "
        f"--fixtures-dir {args.out / 'faults'}\n"
        "  DATABASE_URL=sqlite:///./x.db python -m hoops_gm\n"
        "  curl .../api/v1/leagues/1/schedule-grid/current > <fixture>.recorded.json\n"
        "Compare against the committed fixture. Everything outside "
        "`refreshed_at` should be identical; if it is not, the producer moved "
        "and that difference is the finding."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
