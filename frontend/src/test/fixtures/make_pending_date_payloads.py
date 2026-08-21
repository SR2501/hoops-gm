"""Derive the payloads behind the three recorded schedule-grid fixtures.

Why this file exists
--------------------

``schedule-grid-date-faults.recorded.json`` and
``schedule-grid-date-absent.recorded.json`` are recordings: real API responses,
captured from a real database, seeded by the real importer. But the *input* that
made the importer produce those four ``date_absence_reason`` values is not
something the NBA has ever sent — all six pending games in the live 2026-27
season carry reconcilable dates, so every non-empty reason fires zero times.
``schedule-grid-current.recorded.json`` is the third, captured from the base
undoctored; it is derived here too, with an empty edit set, so the payload the
other two are edits *of* is itself pinned to a recording.

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
fixture's ``pending_game_ids``, compares **every field of every pending record**
against the recording, recomputes all 630 per-period per-team count rows, and
checks the lineage counters. If the producer reorders reconciliation and
plausibility, a 1900 pair stops being ``implausible`` — the frozen fixture would
not notice, and this does. If somebody hand-edits a reason in the JSON, that
fails here too, which is the conversion-into-a-mock this whole file exists to
prevent.

The comparison is whole-record rather than field-by-field because three separate
probes found this check **green while pointed at something it was not looking
at** — the wrong base, a hardcoded expectation dict, then only the pending block
while a resolved game moved period. Each fix closed the instance and left the
next field open, and the fourth one found was ``game_date``: the field that
decides which column carries the TBD marker, computed here and discarded. A
field added to the contract now arrives as a mismatch rather than as silence.

What this check can and cannot see
---------------------------------

The rule that found every one of those holes, from ``architect``: **anything a
check reads out of the artifact it is checking cannot fail.** Run to exhaustion
over the response's six top-level keys rather than one field per round, so the
next person does not have to rediscover where the floor is:

===================== ===========================================================
``counts``            **derived** — all 630 rows, from the payload.
``lineage.schedule``  **partly derived** — ``source_game_count``,
                      ``resolved_game_count`` and every ``pending_games`` field.
                      ``persisted_team_row_count`` is covered transitively by the
                      producer's ``persisted == 2 x resolved`` invariant.
                      ``unresolved_game_ids`` is ``[]`` in all three recordings
                      and the counts identity pins only *that it is empty* — if
                      it were ever non-empty this row would be false.
                      ``refresh_id``, ``refreshed_at`` and the content-version
                      fingerprint need a database: tried, no pure function found.
                      (``lineage``'s three other children are the same database
                      artifacts and none is rendered by the grid.)
``periods``           **derived** — all 21 windows including ``is_playoff``, via
                      ``weekly_periods``. Be precise, because the property here
                      is stronger than anything else in this file.
                      ``weekly_periods`` is not the producer and not a second
                      implementation of it: it is the **seed's input** to the
                      production transform, which is
                      ``calendar/scoring_periods.py``'s
                      ``project_scoring_periods``, and that is what writes the
                      rows the response reports. So the comparison *spans*
                      production code. Change how periods are projected,
                      re-capture, and this still fails — because the derived side
                      does not move with the producer. Every other check here,
                      ``parse_schedule`` above all, **is** the production
                      transform, so a faithful re-capture reproduces a producer
                      change invisibly. This one is the exception.
                      It was read out of the recording for three rounds, and it
                      is the other operand of the computation hole four was
                      about: ``readPendingGames`` needs a pending date *and* a
                      period window, and only the date was pinned. The counts
                      could not object, because 610 of 630 rows are zero and only
                      two periods hold a resolved game, so the December boundary
                      that decides this feature sat in free space.
``teams``             **derived** for ``nba_team_id``, ``abbreviation`` and
                      ``name``, from ``nba_static_teams.json``, membership
                      first. ``team_id`` is assigned by seeding — **tried and no
                      pure function found**, which is a weaker claim than "out of
                      reach" and is the honest one after a floor turned out to be
                      one import lower.
``season``            **legitimately an input.** It names which season to parse.
``league_id``         assigned by seeding, same category as ``team_id``: tried,
                      no pure function found. Not the same thing as ``season``'s
                      legitimacy, which is why they are no longer phrased alike.
===================== ===========================================================

Two of those rows said *"an input, and this is the floor"* one commit ago, on my
own reasoning that scoring periods come only from SQL. A reviewer went and found
``weekly_periods`` and drove the closure. **The floor was one function lower than
I claimed**, and asserting where a method stops is exactly as falsifiable as
asserting anything else — so every row above says *tried* rather than
*impossible*.

One thing the table's shape hides, and it is where a seventh would live: every
row is about a **value** being wrong. The sixth hole was a **cardinality** and
the seventh a **key set** — teams could be added upstream or deleted from a
recording, and a non-zero count row could be overwritten by a duplicate zero row
while the total stayed at 630. Each passed because a comparison checked the
values of a set whose membership the artifact under test declared.

`frontend`'s procedure is what replaced guessing, and it is the thing to apply
next rather than another field: **for each thing this file compares, what is the
key set, and is it asserted or assumed?** Every hole so far has been an answer of
"assumed". Membership is now asserted for the response's top-level keys, the
recordings on disk, pending record fields, pending ids, periods, teams, and the
630 (period, team) pairs.

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
#: The response's top-level keys, one row each in the audit table above. Named
#: so the table is an assertion rather than a prose claim about an assertion.
RESPONSE_KEYS = frozenset({"league_id", "season", "lineage", "teams", "periods", "counts"})

RECORDED = {
    # Undoctored: the base as committed, which every other comparison is
    # anchored on. Included so `--verify` pins the payload the other two are
    # edits *of*, and so the loop below covers every recording in this
    # directory rather than only the ones with edits.
    "current": pathlib.Path(__file__).parent / "schedule-grid-current.recorded.json",
    "faults": pathlib.Path(__file__).parent / "schedule-grid-date-faults.recorded.json",
    "absent": pathlib.Path(__file__).parent / "schedule-grid-date-absent.recorded.json",
}


def recorded_expectations(variant: str) -> tuple[list[str], dict[str, dict]]:
    """The pending ids and the *whole* pending record each fixture holds.

    Not just the reason. Three separate probes found this function checking one
    field at a time -- reason only, then reason plus counts -- and each time the
    next unchecked field was the one that mattered. ``game_date`` was computed
    and thrown away into ``_``, which is the field ``readPendingGames`` buckets
    on to decide which column carries the TBD marker: both pending games could
    move a week, reconcile cleanly, and this printed success while the marker
    landed on a different period than the recording shows.

    So it compares every field of the record, over the **union** of the two key
    sets. Iterating only the recording's keys was the first version, and its
    docstring claimed the one direction it did not cover: a field *added* to the
    contract is absent from an older recording, so nothing yields it, so nothing
    looks. Both reviewers drove it by deleting a field from the recordings and
    getting exit 0. A field appearing or vanishing is now a mismatch either way.
    """
    schedule = json.loads(RECORDED[variant].read_text(encoding="utf-8"))["lineage"]["schedule"]
    records = {game["nba_game_id"]: game for game in schedule["pending_games"]}
    return list(schedule["pending_game_ids"]), records


def recorded_counts(variant: str) -> tuple[dict, list[dict], list[dict]]:
    fixture = json.loads(RECORDED[variant].read_text(encoding="utf-8"))
    return fixture, fixture["periods"], fixture["counts"]


def derived_counts(payload: dict, periods: list[dict], teams: list[dict], season: str) -> dict:
    """Per-period per-team game counts implied by the derived payload.

    **Half of this is the producer's and half is a reproduction, and the halves
    matter differently.** Dates come from the producer's own ``parse_schedule``,
    so a change to how it resolves a date fails here instead of being faithfully
    re-derived by a second copy of that logic. The *period assignment* below is
    not the producer's: the response's ``counts`` come from a SQL query over
    ``ScoringPeriod`` rows, and this is an inclusive string-range scan written
    here. `schedule_grid.py` names that hazard as its reason for refusing the
    same duplication -- a second definition free to drift from the one that
    produced the numbers.

    It is accepted here because the alternative is standing up a database to run
    one check, and because drift shows up as a mismatch against a recording that
    *was* produced by the SQL. But if these ever disagree, this file is the more
    likely one to be wrong.

    **The boundaries the scan uses are passed in, and are checked separately.**
    ``periods`` comes from the recording here, so on its own this would answer
    *are the games where the recording says, given the recording's columns*
    rather than *are the columns right*. That was true for three rounds and a
    reviewer drove it: shift every boundary three days and 6 of 630 rows move
    while everything stayed green. ``verify`` now derives the windows from
    ``weekly_periods`` and compares them before calling this, so the columns are
    pinned by the producer rather than assumed. Keep it that way -- this
    function is only sound because its caller checks its inputs.
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
    from hoops_gm.dev.seed_schedule_grid import weekly_periods
    from hoops_gm.ingest.nba.parsers import parse_teams
    from hoops_gm.ingest.nba.schedule import parse_schedule

    if set(RECORDED) != set(VARIANTS):
        raise SystemExit(
            f"every recording must have a variant and vice versa; "
            f"recordings-only {sorted(set(RECORDED) - set(VARIANTS))}, "
            f"variants-only {sorted(set(VARIANTS) - set(RECORDED))}. "
            "A recording with no variant is skipped silently, which is the "
            "defect this function keeps being caught by."
        )

    # ...and that assertion is between two hardcoded dicts, so a fourth
    # recording dropped into this directory is absent from *both* and passes.
    # The comment on RECORDED claims directory coverage; this is what makes the
    # claim true rather than coincidental.
    on_disk = set(pathlib.Path(__file__).parent.glob("schedule-grid-*.recorded.json"))
    if on_disk != set(RECORDED.values()):
        raise SystemExit(
            "a schedule-grid recording exists that no variant derives: "
            f"{sorted(p.name for p in on_disk - set(RECORDED.values()))}. "
            "Add it to RECORDED and VARIANTS, or it is a recording nothing checks."
        )

    failures = 0
    for variant in VARIANTS:
        recorded_ids, expected = recorded_expectations(variant)
        fixture, periods, counts = recorded_counts(variant)
        season = fixture["season"]
        # The audit table below is exhaustive over the response's top-level keys
        # *as the recording currently has them*, and nothing enforced that there
        # were six. This is the pending record's key-set union one level up: I
        # closed it for the leaf and left it assumed at the root.
        if set(fixture) != RESPONSE_KEYS:
            failures += 1
            print(
                f"FAIL {variant:7} response shape changed: "
                f"unexpected {sorted(set(fixture) - RESPONSE_KEYS)}, "
                f"missing {sorted(RESPONSE_KEYS - set(fixture))}. The per-key "
                "audit in this module's docstring is now incomplete."
            )
            continue
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

        for pending in parse_schedule(payload, season=season).pending_games:
            record = expected[pending.nba_game_id]
            derived_record = {
                "nba_game_id": pending.nba_game_id,
                "game_date": pending.game_date.isoformat() if pending.game_date else None,
                "game_label": pending.game_label,
                "game_sub_label": pending.game_sub_label,
                "game_subtype": pending.game_subtype,
                "date_absence_reason": pending.date_absence_reason,
            }
            differing = {
                field: (record.get(field, "<absent>"), derived_record.get(field, "<absent>"))
                for field in set(record) | set(derived_record)
                if record.get(field, "<absent>") != derived_record.get(field, "<absent>")
            }
            if differing:
                failures += 1
                detail = "; ".join(
                    f"{field}: recorded {rec!r} derived {der!r}"
                    for field, (rec, der) in differing.items()
                )
                print(f"FAIL {variant:7} {pending.nba_game_id}  {detail}")
            else:
                print(
                    f"ok  {variant:7} {pending.nba_game_id}  every recorded field reproduced "
                    f"(date {record['game_date']!r}, reason {record['date_absence_reason']!r})"
                )

        # The resolved ten twelfths. Pinning only the pending block left a
        # resolved game free to move between scoring periods -- a within-DST
        # shift that reconciles cleanly -- while this printed success.
        # Completeness is a claim about *which* (period, team) pairs are present,
        # and asserting it by row count was a proxy that came apart. Overwrite
        # one non-zero row with a duplicate of a zero row: still 630 rows, dense
        # check passes, and because the comparison iterates recorded rows the
        # vanished pair is never looked up. That one reaches the screen -- the
        # client deliberately tolerates a sparse `counts` rather than blanking
        # the page, so the missing pair renders as `·`, which asserts *the
        # backend sent no count*. A real number would become a marker claiming
        # the opposite. The recorded test shared the blind spot, because it
        # asserts the same length.
        expected_keys = {
            (period["period_number"], team["team_id"])
            for period in periods
            for team in fixture["teams"]
        }
        recorded_keys = {(row["period_number"], row["team_id"]) for row in counts}
        if recorded_keys != expected_keys:
            failures += 1
            print(
                f"FAIL {variant:7} counts is not the dense {len(periods)}x"
                f"{len(fixture['teams'])} cross product: {len(counts)} rows, "
                f"{len(recorded_keys)} distinct pairs, "
                f"{len(expected_keys - recorded_keys)} missing, "
                f"{len(recorded_keys - expected_keys)} unexpected."
            )
            continue

        # `periods` and `teams` were both read out of the artifact under test,
        # so a recording that lied about its own columns was used to check
        # itself. `periods` is the other operand of the computation hole four
        # was about: `readPendingGames` needs a pending date *and* a period
        # window to choose the TBD column, and only the first was pinned. Move
        # period 6's boundary past 2026-12-04 and the marker lands on a
        # different column with every other check still green -- and the counts
        # comparison cannot object, because 610 of 630 rows are zero and only
        # two periods hold a resolved game, so the December boundary sits in
        # free space.
        parsed = parse_schedule(payload, season=season)
        game_days = sorted(record.game.game_date for record in parsed.games)
        derived_periods = [
            {
                "period_number": number,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "is_playoff": is_playoff,
            }
            for number, start, end, is_playoff in weekly_periods(game_days[0], game_days[-1])
        ]
        if derived_periods != periods:
            failures += 1
            if len(derived_periods) != len(periods):
                print(
                    f"FAIL {variant:7} period count differs: {len(periods)} recorded, "
                    f"{len(derived_periods)} derived."
                )
            else:
                head = next(
                    (rec, der)
                    for rec, der in zip(periods, derived_periods, strict=True)
                    if rec != der
                )
                differing_rows = [
                    1 for rec, der in zip(periods, derived_periods, strict=True) if rec != der
                ]
                print(
                    f"FAIL {variant:7} {len(differing_rows)} period row(s) differ; "
                    f"first recorded {head[0]} derived {head[1]}."
                )
        else:
            print(f"ok  {variant:7} all {len(periods)} period windows reproduced")

        derived_teams = {
            team.nba_team_id: (team.abbreviation, team.full_name)
            for team in parse_teams(json.loads(TEAMS.read_text(encoding="utf-8")))
        }
        # Compare membership before values. Iterating the recording and reading
        # `derived_teams.get(...)` is `recording subset derived` -- the same
        # one-directionality closed for pending records one function earlier and
        # reintroduced here. Both directions were driven: a 31st team added
        # upstream was silent, and half the league could be *deleted* from a
        # recording along with its zero count rows, because the density
        # assertion multiplies by the array under test. Cardinality is the class
        # every earlier fix missed -- each compared the values of a set whose
        # membership the artifact under test declared.
        recorded_team_ids = {team["nba_team_id"] for team in fixture["teams"]}
        if recorded_team_ids != set(derived_teams):
            failures += 1
            print(
                f"FAIL {variant:7} team membership differs: "
                f"{len(recorded_team_ids)} recorded, {len(derived_teams)} derived; "
                f"recorded-only {sorted(recorded_team_ids - set(derived_teams))}, "
                f"derived-only {sorted(set(derived_teams) - recorded_team_ids)}."
            )
        team_mismatches = [
            team
            for team in fixture["teams"]
            if derived_teams.get(team["nba_team_id"]) != (team["abbreviation"], team["name"])
        ]
        if team_mismatches:
            failures += 1
            head = team_mismatches[0]
            print(
                f"FAIL {variant:7} {len(team_mismatches)} team row(s) differ; first is "
                f"{head['nba_team_id']}: recorded {(head['abbreviation'], head['name'])}, "
                f"derived {derived_teams.get(head['nba_team_id'])}."
            )
        else:
            print(f"ok  {variant:7} all {len(fixture['teams'])} team labels reproduced")

        derived = derived_counts(payload, derived_periods, fixture["teams"], season)
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

        # Games outside every scoring period contribute to no count row, so the
        # comparison above cannot see one appearing or vanishing. The lineage
        # counters can, and they are already in the recording.
        parsed = parse_schedule(payload, season=season)
        lineage = fixture["lineage"]["schedule"]
        for label, derived_value, recorded_value in (
            ("source_game_count", parsed.source_game_count, lineage["source_game_count"]),
            ("resolved_game_count", len(parsed.games), lineage["resolved_game_count"]),
            # These two were left out as "covered transitively by producer
            # invariants", which is a false disposition: an invariant guarantees
            # the *producer* will not emit a bad value, and this file's stated
            # threat is a hand-edit to a committed recording. So the two fields
            # most strongly guaranteed upstream were the two the recording could
            # lie about most freely. Both are one line and neither needs a
            # database -- `persisted == 2 x resolved` is arithmetic on a number
            # three lines up.
            ("unresolved_game_ids", [], lineage["unresolved_game_ids"]),
            (
                "persisted_team_row_count",
                2 * len(parsed.games),
                lineage["persisted_team_row_count"],
            ),
        ):
            if derived_value != recorded_value:
                failures += 1
                print(
                    f"FAIL {variant:7} {label}: recorded {recorded_value}, derived {derived_value}."
                )

    if failures:
        print(
            f"\n{failures} check(s) failed. Either the producer's classification moved, "
            "in which case re-capture rather than editing the JSON, or a fixture was "
            "hand-edited, in which case it has stopped being a recording."
        )
    else:
        print(
            "\nEvery recorded pending record, period window, team label, count row "
            "and lineage counter is reproduced by the in-tree producer."
        )
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
