"""Re-derive the consensus-reproducibility measurements from cache, offline.

Committed because the *first* run of these measurements was not. A procedure
that lives only in a shell transcript has to be reinvented by whoever next
doubts the number, and reinventing it is how ``docs/backlog.md`` came to quote a
rates-only range beside a games-played conclusion for a day without anyone being
able to check it cheaply. This script is the cheap check.

It answers four questions, each a subcommand:

``rates``
    Which columns is the cited ``r² 0.726-0.947`` drawn from? Re-derives the
    crudest baseline in ``docs/models/consensus-reproducibility.md`` — last
    season's per-game line carried forward, no modelling — and reports rates,
    minutes and games as three separate channels.

``divisor``
    Does consuming a source's per-game rate inherit the games tier we rejected?
    ADR-002's amendment of 2026-08-23 turns on this.

``concentration``
    How much per-player opinion does a source column actually carry? This is the
    test that condemned ``games`` and had never been pointed at ``minutes``.

``leak-scan``
    Does this unit's committed prose contain a mode or an extremum of a paid
    column?

**Nothing here fits anything.** There is no model, no held-out year and no
player-level number, so no Model gate is claimed. Every figure is an *agreement*
between two opinions; neither side is ground truth.

**Boundaries this script does not cross, each because something went wrong when
it was crossed before:**

* It never discovers a path. The paid export is named by
  ``HOOPS_GM_BBM_PROJECTION_CSV`` and the script refuses without it, matching
  the adapter boundary in ``docs/adapters/basketball-monster-projections.md``.
  The private path is not committed here and must not be.
* It never makes a network request. The public side is read from the recorded
  ``RawPayloadStore``; a missing capture is a refusal, not a fetch.
* Nothing it prints is a paid cell. Correlations, counts and shares only — never
  a mode, a minimum or a maximum of a paid column, because a mode is the one
  summary statistic guaranteed to be a verbatim cell and two of them leaked that
  way on 2026-08-22.
* Its controls must fire or the run is declared invalid. A shuffled-divisor
  control that does not land near chance, or a leak-scan tripwire that does not
  trip, means the measurement proves nothing — and a harness that reports
  success about nothing is the defect class this repository keeps finding.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import os
import random
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend" / "src"))

from hoops_gm.ingest.projections.models import ProjectionSourceRow  # noqa: E402
from hoops_gm.ingest.projections.parser import parse_projection_csv  # noqa: E402
from hoops_gm.ingest.projections.profiles import (  # noqa: E402
    BASKETBALL_MONSTER_PROFILE,
)
from hoops_gm.ingest.rawstore import RawPayloadStore  # noqa: E402

#: Pinned in ``docs/adapters/basketball-monster-projections.md``. The export is
#: identified by content, never by filename — a file named
#: ``2026-27-projections.csv`` is a claim about itself.
PINNED_SHA = "FA13AD188E8ACADD410DFEAE7FF296A25078842E22CE17046CF19DFBCA9D3ABD"

CSV_ENV = "HOOPS_GM_BBM_PROJECTION_CSV"
RAW_ROOT_ENV = "HOOPS_GM_RAW_ROOT"

#: The season whose observed line is carried forward. A commercial 2026-27
#: projection is built with 2025-26 in hand, so a baseline stopping earlier is a
#: year stale and every disagreement is partly that artefact rather than a
#: difference of opinion.
BASELINE_SEASON = "2025-26"

#: The nine scored categories, with the two percentage categories expanded into
#: their volume components — a percentage category is volume-weighted impact and
#: not a raw percentage, so FG% enters as FGM and FGA rather than as a ratio.
#: ``minutes`` and ``games`` are deliberately **not** here; that separation is
#: the whole point of the ``rates`` subcommand.
RATE_CATEGORIES: dict[str, str] = {
    "PTS": "points_per_game",
    "REB": "rebounds_per_game",
    "AST": "assists_per_game",
    "STL": "steals_per_game",
    "BLK": "blocks_per_game",
    "TOV": "turnovers_per_game",
    "FG3M": "three_pointers_made_per_game",
    "FGM": "field_goals_made_per_game",
    "FGA": "field_goals_attempted_per_game",
    "FTM": "free_throws_made_per_game",
    "FTA": "free_throws_attempted_per_game",
}

LOG_COLUMNS = (
    "MIN",
    "PTS",
    "REB",
    "AST",
    "STL",
    "BLK",
    "TOV",
    "FG3M",
    "FGM",
    "FGA",
    "FTM",
    "FTA",
)

#: Cohorts are selected on **our** observed minutes at every threshold, never on
#: a commercial value. Selecting on the quantity being measured would make the
#: measurement about the selection.
COHORTS: tuple[tuple[str, float], ...] = (
    ("all joined", 0.0),
    ("our MPG >= 10", 10.0),
    ("our MPG >= 20", 20.0),
    ("our MPG >= 28", 28.0),
)

MIN_COHORT = 20
SEED = 20260823


class Refusal(SystemExit):
    """Raised instead of degrading a measurement into a weaker one."""

    def __init__(self, message: str) -> None:
        super().__init__(f"REFUSED: {message}")


# --- loading -----------------------------------------------------------------


def load_export() -> list[ProjectionSourceRow]:
    """Parse the paid export through the production adapter, not a copy of it."""
    raw = os.environ.get(CSV_ENV)
    if not raw:
        raise Refusal(
            f"{CSV_ENV} is not set. This script never discovers a path to a paid "
            "export; point it at one explicitly or do not run it."
        )
    path = Path(raw)
    if not path.is_file():
        raise Refusal(f"{CSV_ENV} does not name a readable file")
    digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    if digest != PINNED_SHA:
        raise Refusal(
            "export content does not match the SHA-256 pinned in "
            "docs/adapters/basketball-monster-projections.md. This is a "
            "different file, whatever it is named; the measurements below "
            "would not be about the export the documents describe."
        )
    parsed = parse_projection_csv(
        path.read_text(encoding="utf-8"), BASKETBALL_MONSTER_PROFILE, season="2026-27"
    )
    return list(parsed.rows)


def load_baseline() -> dict[str, dict[str, float]]:
    """Observed per-game line for ``BASELINE_SEASON``, from the recorded store.

    Cache-only. A missing capture refuses rather than fetching: this script is
    run to check a number, and a check that quietly makes eleven throttled
    requests against an unstable upstream is not cheap enough to be run.
    """
    root = Path(os.environ.get(RAW_ROOT_ENV, "data/raw"))
    if not root.is_dir():
        raise Refusal(
            f"no recorded payload store at {root}. Set {RAW_ROOT_ENV} to one. "
            "This script does not fetch."
        )
    store = RawPayloadStore(root)
    ref = store.latest(
        source="nba_stats",
        endpoint="PlayerGameLogs",
        params={
            "season_nullable": BASELINE_SEASON,
            "season_type_nullable": "Regular Season",
        },
    )
    if ref is None:
        raise Refusal(
            f"no recorded PlayerGameLogs capture for {BASELINE_SEASON} regular "
            f"season under {root}. This script does not fetch; record one first."
        )
    payload: Any = ref.read_json()
    result_sets = payload["resultSets"]
    rs = result_sets[0]
    index = {header: position for position, header in enumerate(rs["headers"])}
    missing = [column for column in ("PLAYER_NAME", *LOG_COLUMNS) if column not in index]
    if missing:
        raise Refusal(f"recorded payload is missing columns {missing}")

    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rs["rowSet"]:
        key = normalise(str(row[index["PLAYER_NAME"]]))
        bucket = totals[key]
        bucket["GP"] += 1.0
        for column in LOG_COLUMNS:
            value = row[index[column]]
            bucket[column] += float(value) if value is not None else 0.0

    observed: dict[str, dict[str, float]] = {}
    for key, bucket in totals.items():
        games = bucket["GP"]
        record = {column: bucket[column] / games for column in LOG_COLUMNS}
        record["GP"] = games
        observed[key] = record
    return observed


def normalise(name: str) -> str:
    text = name.lower().replace(".", "").replace("'", "").replace("-", " ")
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


# --- statistics --------------------------------------------------------------


def r_squared(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < MIN_COHORT:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    return (covariance / math.sqrt(var_x * var_y)) ** 2


def on_grid(value: float, places: int) -> bool:
    scaled = value * (10.0**places)
    return bool(abs(scaled - round(scaled)) < 1e-6)


def effective_levels(values: list[float]) -> float:
    """1 / sum(p^2): how many distinct values a uniform column would need.

    Reported instead of a distinct-value count because the two columns this
    exists to compare take the **same** number of distinct values and differ
    sixfold here. A count would have called them identical.
    """
    n = len(values)
    counts = Counter(values)
    return 1.0 / sum((count / n) ** 2 for count in counts.values())


# --- subcommands -------------------------------------------------------------


def cmd_rates() -> int:
    rows = load_export()
    observed = load_baseline()
    print(f"parsed export rows: {len(rows)}")
    print(f"players with a {BASELINE_SEASON} log: {len(observed)}")

    joined: list[tuple[dict[str, float], ProjectionSourceRow]] = []
    for row in rows:
        mine = observed.get(normalise(row.player_name))
        if mine is not None:
            joined.append((mine, row))
    print(f"joined on exact normalised name: {len(joined)} of {len(rows)}")
    if len(joined) < MIN_COHORT:
        raise Refusal("join produced too few rows to report anything")

    channels = {**RATE_CATEGORIES, "MIN": "minutes_per_game"}
    results: dict[str, dict[str, float]] = {}
    for label, floor in COHORTS:
        pool = [pair for pair in joined if pair[0]["MIN"] >= floor]
        row_out: dict[str, float] = {}
        for short, field in channels.items():
            xs: list[float] = []
            ys: list[float] = []
            for mine, theirs in pool:
                value = getattr(theirs, field)
                if value is None:
                    continue
                xs.append(mine[short])
                ys.append(float(value))
            got = r_squared(xs, ys)
            if got is not None:
                row_out[short] = got
        xs, ys = [], []
        for mine, theirs in pool:
            if theirs.assumed_games_played is None:
                continue
            xs.append(mine["GP"])
            ys.append(theirs.assumed_games_played)
        got = r_squared(xs, ys)
        if got is not None:
            row_out["GAMES"] = got
        results[label] = row_out
        print(f"  cohort {label!r}: n = {len(pool)}")

    order = [*RATE_CATEGORIES, "MIN", "GAMES"]
    print()
    print("r2, carry-forward baseline against the commercial set")
    print(" | ".join([f"{'cohort':>14}"] + [f"{key:>5}" for key in order]))
    for label, row_out in results.items():
        cells = [f"{label:>14}"] + [
            (f"{row_out[key]:.3f}" if key in row_out else "  -  ").rjust(5) for key in order
        ]
        print(" | ".join(cells))

    def span(keys: list[str]) -> tuple[float, float]:
        pool = [row_out[key] for row_out in results.values() for key in keys if key in row_out]
        return min(pool), max(pool)

    rate_lo, rate_hi = span(list(RATE_CATEGORIES))
    min_lo, min_hi = span(["MIN"])
    gp_lo, gp_hi = span(["GAMES"])
    print()
    print(f"{len(RATE_CATEGORIES)} rate categories : r2 {rate_lo:.3f} - {rate_hi:.3f}")
    print(f"minutes              : r2 {min_lo:.3f} - {min_hi:.3f}")
    print(f"games                : r2 {gp_lo:.3f} - {gp_hi:.3f}")
    print()
    if gp_hi >= rate_lo:
        print(
            "NOTE: games agreement reaches the rate floor in this run. The "
            "citation argument in docs/models/consensus-reproducibility.md "
            "assumes it does not, and should be re-read."
        )
    else:
        print(
            "The three channels do not overlap. A cited range whose floor is the "
            "rate floor therefore cannot contain the games channel, which is what "
            "settles whether that citation covers games."
        )
    return 0


def cmd_divisor() -> int:
    """Is a consumed per-game rate free of the source's games assumption?"""
    rows = load_export()
    usable: list[tuple[float, float, ProjectionSourceRow]] = []
    for row in rows:
        games = row.assumed_games_played
        raw_minutes = row.raw_row.get("minutes")
        if not games or not raw_minutes:
            continue
        try:
            minutes_total = float(raw_minutes)
        except ValueError:
            continue
        if minutes_total > 0:
            usable.append((games, minutes_total, row))
    n = len(usable)
    print(f"rows carrying both a games figure and a minutes total: {n}")
    if n < MIN_COHORT:
        raise Refusal("too few usable rows")

    shuffled = [minutes for _, minutes, _ in usable]
    random.Random(SEED).shuffle(shuffled)

    exact = sum(1 for games, minutes, _ in usable if on_grid(minutes / games, 0))
    control = sum(
        1
        for i, (_, minutes, _) in enumerate(usable)
        if on_grid(minutes / max(shuffled[i] / 30.0, 1.0), 1)
    )
    exact_pct = 100.0 * exact / n
    control_pct = 100.0 * control / n
    print()
    print(f"minutes / games is an exact integer : {exact} of {n} ({exact_pct:.1f}%)")
    print(f"shuffled-divisor control            : {control_pct:.1f}%")
    # Compare percentage against percentage. The first version of this guard
    # compared the raw *count* against 50.0 and refused a valid run at 10.9%,
    # which is this repository's own defect class arriving inside the check
    # written to prevent it: a units error in a guard is invisible until the
    # guard fires, and it could as easily have passed vacuously.
    if control_pct > 50.0:
        raise Refusal(
            "the shuffled control also lands on the grid for most rows, so this "
            "test discriminates nothing here and its result is not evidence"
        )

    print()
    print("share landing on a short-decimal grid, by divisor")
    print(f"{'column':>14} | {'TOTAL 1dp':>9} | {'/games':>7} | {'/min x36':>8} | {'shuffled':>8}")
    counting = list(BASKETBALL_MONSTER_PROFILE.expected_headers or ())
    for header in counting:
        if header in ("player_id", "first_name", "last_name", "games", "comments"):
            continue
        totals: list[float] = []
        for _, _, row in usable:
            value = row.raw_row.get(header)
            try:
                totals.append(float(value) if value is not None else math.nan)
            except ValueError:
                totals.append(math.nan)
        if any(math.isnan(value) for value in totals):
            continue
        t1 = sum(1 for value in totals if on_grid(value, 1))
        by_games = sum(1 for i, value in enumerate(totals) if on_grid(value / usable[i][0], 1))
        by_minutes = sum(
            1 for i, value in enumerate(totals) if on_grid(36.0 * value / usable[i][1], 1)
        )
        by_shuffled = sum(
            1 for i, value in enumerate(totals) if on_grid(36.0 * value / shuffled[i], 1)
        )
        print(
            f"{header:>14} | {100 * t1 / n:8.1f}% | {100 * by_games / n:6.1f}%"
            f" | {100 * by_minutes / n:7.1f}% | {100 * by_shuffled / n:7.1f}%"
        )
    print()
    print(
        "A column whose real divisor is recoverable stands clear of the shuffled\n"
        "control. A column at chance against every candidate is undetermined -\n"
        "publication rounding has destroyed the signature - and 'undetermined' is\n"
        "not 'clean'. ADR-002's amendment turns on which of those two it is."
    )
    return 0


def cmd_concentration() -> int:
    """Ask the coarseness question of both columns, not just the suspected one."""
    rows = load_export()
    pairs = [
        (row.assumed_games_played, row.minutes_per_game)
        for row in rows
        if row.assumed_games_played and row.minutes_per_game is not None
    ]
    print(f"rows carrying both columns: {len(pairs)}")
    print()
    print(
        f"{'column':>18} | {'cohort':>16} | {'n':>4} | {'distinct':>8}"
        f" | {'top2':>6} | {'eff. levels':>11}"
    )
    for label, floor in (("whole file", None), ("their MPG >= 20", 20.0)):
        pool = pairs if floor is None else [pair for pair in pairs if pair[1] >= floor]
        if len(pool) < MIN_COHORT:
            continue
        for name, values in (
            ("games", [games for games, _ in pool]),
            ("minutes-per-game", [minutes for _, minutes in pool]),
        ):
            counts = Counter(values).most_common()
            top2 = sum(count for _, count in counts[:2]) / len(values)
            print(
                f"{name:>18} | {label:>16} | {len(values):4d} | {len(counts):8d}"
                f" | {100 * top2:5.1f}% | {effective_levels(values):11.1f}"
            )
    integral = sum(1 for _, minutes in pairs if on_grid(minutes, 0))
    print()
    print(f"minutes-per-game values that are exact integers: {integral} of {len(pairs)}")
    print()
    print(
        "Distinct-value count alone does not separate these columns - in the\n"
        "rotation cohort they take the same number of distinct values. All the\n"
        "discrimination is in concentration, which is why effective levels is\n"
        "the reported statistic and a count is not."
    )
    return 0


def _paid_candidates(path: Path) -> tuple[set[str], set[str]]:
    """Modes and extremes of every paid column, plus paid name tokens.

    Modes and extremes specifically, because a mode is the one summary statistic
    guaranteed to be a verbatim cell and a mean almost never is. Screening every
    number that merely *appears* in the file was tried and discarded: a
    season-totals export contains nearly every small integer, so that scan
    returns hundreds of hits and tests nothing.
    """
    reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
    columns: dict[str, list[str]] = defaultdict(list)
    names: set[str] = set()
    for row in reader:
        for key, value in row.items():
            if key in ("first_name", "last_name"):
                if value and len(value) >= 3:
                    names.add(value.lower())
                continue
            if key in ("player_id", "comments") or not value:
                continue
            columns[key].append(value)

    numbers: set[str] = set()
    for values in columns.values():
        try:
            floats = [float(value) for value in values]
        except ValueError:
            continue
        for value, _ in Counter(values).most_common(3):
            numbers.add(value.strip())
        for extreme in (min(floats), max(floats)):
            numbers.add(f"{extreme:g}")
            if extreme == int(extreme):
                numbers.add(str(int(extreme)))
    # Deliberate narrowing, stated rather than silent. A season-totals export has
    # counting columns whose *mode* is a single digit, and those match any English
    # prose containing "clause 4" or "6x" — five of the first six hits this scan
    # ever produced were exactly that. Keeping them reproduces the useless
    # hundreds-of-hits scan through a narrower door. A one-digit value also
    # carries no identifying information: it cannot be attributed to a column, a
    # row or a player. The cost is real and accepted: a genuine single-digit leak
    # would pass here.
    return {value for value in numbers if len(value.replace(".", "").lstrip("0")) >= 2}, names


def cmd_leak_scan(base: str) -> int:
    raw = os.environ.get(CSV_ENV)
    if not raw:
        raise Refusal(f"{CSV_ENV} is not set")
    path = Path(raw)
    if hashlib.sha256(path.read_bytes()).hexdigest().upper() != PINNED_SHA:
        raise Refusal("export content does not match the pinned SHA-256")

    numbers, names = _paid_candidates(path)
    print(f"candidate set: {len(numbers)} numeric, {len(names)} name tokens")
    if len(numbers) < 20 or len(names) < 200:
        raise Refusal(
            "candidate set is implausibly small. A guard that iterates an empty "
            "set passes every input, which is how a 330-file secret scan once "
            "covered nothing."
        )

    diff = subprocess.run(
        ["git", "--no-pager", "diff", base, "--", "docs/"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    added = "\n".join(
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    print(f"text under test: {len(added)} chars of added documentation lines")
    if not added.strip():
        raise Refusal(
            f"nothing added against {base}, so the scan's scope excludes the "
            "thing under test and it would pass vacuously"
        )

    def scan(text: str) -> list[str]:
        hits: list[str] = []
        tokens = set(re.findall(r"\d+(?:\.\d+)?", text))
        lowered = text.lower()
        hits.extend(f"numeric {value!r}" for value in numbers if value in tokens)
        hits.extend(
            f"paid name {name!r}" for name in names if re.search(rf"\b{re.escape(name)}\b", lowered)
        )
        return hits

    planted = sorted(numbers)[len(numbers) // 2]
    if not any(planted in hit for hit in scan(f"{added}\nplanted {planted}\n")):
        raise Refusal("tripwire did not fire; this scan proves nothing")
    print("tripwire fired on a planted candidate: the scan is live")

    hits = sorted(set(scan(added)))
    print()
    if not hits:
        print("0 hits.")
        return 0
    print(f"{len(hits)} coincidence(s), every one to be adjudicated by hand:")
    for hit in hits:
        print(f"  - {hit}")
    print()
    print(
        "Hits are not automatically leaks and this command does not decide.\n"
        "Known benign classes, each seen: a cohort size computed from public\n"
        "logs coinciding with a paid column's maximum, and a paid surname that\n"
        "is an ordinary English word firing on prose. Both are left firing on\n"
        "purpose - suppressing them would trade a false positive someone can\n"
        "see for a false negative nobody can."
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("rates", help="which columns the cited r2 range covers")
    sub.add_parser("divisor", help="does a consumed rate inherit the games tier")
    sub.add_parser("concentration", help="how much opinion a source column carries")
    leak = sub.add_parser("leak-scan", help="paid modes/extremes in added docs")
    leak.add_argument("--base", default="origin/main")
    args = parser.parse_args(argv)

    if args.command == "rates":
        return cmd_rates()
    if args.command == "divisor":
        return cmd_divisor()
    if args.command == "concentration":
        return cmd_concentration()
    return cmd_leak_scan(str(args.base))


if __name__ == "__main__":
    sys.exit(main())
