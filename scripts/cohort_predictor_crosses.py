"""Re-derive three predictor crosses over the committed 2025-26 cohort.

Committed because the numbers it prints existed **only in a chat window**, and
one of them underpins a claim in
``docs/models/injury-status-conversion-preregistration-v3-PROPOSED.md`` whose
author described it as *"the weakest link in v3 - a number I will be graded
against, asserted on my authority, with no table behind it."* A cross that
cannot be recomputed is an assertion wearing a table's clothes.

The three crosses, and why each exists
--------------------------------------

``reason x status``
    ``stated_reason_categories`` is committed as a **marginal only**; the cross
    with status is nowhere. It matters because roughly one in five ``doubtful``
    observations is a **G League** row - a Two-Way player who might be recalled.
    That is real uncertainty and a **roster mechanic, not a health event**, and
    its conversion rate has no reason to resemble injury-``doubtful``. Stripping
    it takes ``doubtful``'s held-out floor from a comfortable-looking 83 to a
    health-reason count in the seventies, against a >=30 requirement. Still
    clear; less headroom than the marginal suggests.

``era x lead-time band``
    Partition composition is committed; this cross is not. It is the sharpest
    evidence for v3's Gap A: the short-lead era files vastly more of its reports
    inside the final hour than the legacy era did, and the holdout is 100%
    short-lead.

``partition x status``
    Included so the two crosses above can be read against the chronological
    split they will be used under, rather than against the whole cohort.

What this script refuses to do
------------------------------

**It queries only ``injury_report_entries`` and ``nba_games``.** Both come in
through committed functions - :func:`games_to_backfill` and
:func:`select_canonical_pregame_observations` - and nothing here opens a table
directly. This is not fastidiousness. The merged store this runs against holds
``player_participation`` in the same file, one line away from every query below,
and v3's entire legality argument rests on that boundary having been held. A
committed script that makes crossing it easy is a standing invitation, so the
boundary is stated here rather than only in the brief that asked for it.

**It emits no outcome, and it must not learn to.** Every quantity printed is a
*report designation* - what the NBA said before tip-off - never what the player
then did.

**If any of these crosses is ever committed as JSON under ``docs/``, it will
pass the section 2 guard silently.** ``outcome_keyed_field_paths`` in
``hoops_gm.ingest.injury_report.cohort_admissibility`` detects fields *keyed* by
a ``ParticipationOutcome`` token. ``reason x status`` is keyed by
``InjuryReportStatus``, which is precisely the guard's blind spot, and section
2's prose forbids outcome-**valued** disclosure that the guard cannot see. These
particular crosses are innocent - they are inputs, not outcomes - which is
exactly what makes them a good test case: they should be classified
**explicitly**, by someone who looked, and never wave through because the
detector did not recognise them. Printing to a terminal rather than writing an
artifact is the current answer; that choice is deliberate and is the reason
there is no ``--out``.

**It is not wired into the test suite, and must not be.** The store is
out-of-tree gitignored operational state, so in CI it is absent: a test over it
would either fail permanently or be made to skip, and **a skipping test is a
green light nobody is holding.** ``scripts/`` sits outside the pytest, ruff and
mypy scopes - all three run with ``working-directory: backend`` - so nothing in
CI executes or lints this file. Whoever changes the selection functions it
depends on will not be told. That is a real cost of the ``--max-requests 120``
rule this script is obeying, and it is written down rather than traded away.

The validation is the load-bearing part
---------------------------------------

Before printing anything, this reproduces the manifest's canonical selection and
asserts **two published marginals** against the committed artifact:
``canonical_observations.status_counts`` and
``reason_evidence.stated_reason_categories``. A mismatch prints both sides and
exits non-zero. **A cross computed by a selection that does not reproduce is
worse than no cross**, because it looks like evidence.

The window, season and season type are read from the manifest's own ``scope``
rather than passed in, so a mismatch cannot be caused by this script being
pointed at a different window than the artifact it checks against.

One thing the crosses are *not* over
------------------------------------

All three are over the **canonical** selection - 13,789 observations, the same
population as ``status_counts``. They are **not** over the *direct* selection of
13,598 that ``direct_outcomes_by_lead_time_band`` uses in the admissibility
artifact. The two differ by the participation join, and mixing them would
produce a table that reconciles with neither. Anything comparing a number here
against that artifact must convert first.

Usage::

    cd backend
    $env:PYTHONPATH = "$PWD\\src"
    $env:DATABASE_URL = "sqlite+pysqlite:///C:/Users/.../cohort-merged-2025-26.db"
    python ../scripts/cohort_predictor_crosses.py

``DATABASE_URL`` is the variable this project actually reads; a
``HOOPS_GM_``-prefixed name is silently swallowed. ``--store`` accepts a bare
filesystem path instead.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend" / "src"))

from sqlalchemy.orm import Session  # noqa: E402

from hoops_gm.db.models.enums import SeasonType  # noqa: E402
from hoops_gm.ingest.injury_report.backfill import (  # noqa: E402
    CanonicalPregameObservation,
    games_to_backfill,
    select_canonical_pregame_observations,
)
from hoops_gm.ingest.injury_report.cohort_admissibility import (  # noqa: E402
    LEAD_TIME_BANDS,
    chronological_split,
    lead_time_band,
    read_only_engine,
    report_era,
)

DEFAULT_MANIFEST = (
    REPO / "docs" / "adapters" / "nba-injury-report-cohort-2025-10-21--2026-04-12.json"
)
DEFAULT_ADMISSIBILITY = (
    REPO / "docs" / "adapters" / "nba-injury-report-cohort-admissibility-2025-26.json"
)

#: Column order for every status-keyed table, worst-to-best rather than
#: alphabetical, because that is the order the reviewer's tables used and a
#: silently reordered column is the cheapest way to misread a cross.
STATUS_ORDER = ("out", "doubtful", "questionable", "probable", "available")

PARTITIONS = ("development", "selection", "held_out")


class Refusal(Exception):
    """A stop with a reason a reader can act on, not a traceback."""


def _store_path(args: argparse.Namespace) -> Path:
    """Name the file this wants, out loud, before anything opens anything.

    A store that is absent, and a store that is present but empty, fail in
    completely different ways: the first is loud, the second answers zero and
    exits successfully. This handles the first and reports the path so the
    second is diagnosable.
    """
    if args.store:
        return Path(args.store).expanduser()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise Refusal(
            "no store to read.\n"
            "  Set DATABASE_URL to the *merged* cohort store, or pass --store <path>.\n"
            "  The merged store is the one carrying both injury_report_entries and\n"
            "  nba_games; the durable ledger alone has no reports and yields an empty\n"
            "  cohort. It is out-of-tree gitignored operational state and is not in any\n"
            "  checkout - on the machine this was written for it lives at\n"
            "    C:\\Users\\steverones\\hoops-gm-data\\cohort-merged-2025-26.db\n"
            "  beside the participation ledger documented in\n"
            "  docs/adapters/participation-ledger-store.md, which is the maintained\n"
            "  source for where these stores live if the path above has moved.\n"
            "  It is built by hoops_gm.ingest.injury_report.merge_stores.\n"
            "  Note the variable name: DATABASE_URL, not HOOPS_GM_DATABASE_URL. A\n"
            "  prefixed name is silently swallowed and reads as 'unset'."
        )
    for prefix in ("sqlite+pysqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return Path(url[len(prefix) :]).expanduser()
    raise Refusal(
        f"DATABASE_URL is {url!r}, which is not a SQLite URL this script can turn "
        "into a path. Pass --store <path> instead."
    )


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise Refusal(
            f"no manifest at {path}. It is committed; a missing one means a bad --manifest."
        )
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _reason_head(observation: CanonicalPregameObservation) -> str | None:
    """The category the report itself printed, before its own separator.

    Reproduced from ``cohort_evidence._reason_evidence`` rather than imported,
    because that function returns an assembled section and not the per-row
    label. It must stay identical to it, which is exactly what the
    ``stated_reason_categories`` assertion below checks - if this drifts, the
    marginal stops reproducing and the run refuses.

    Empty reason text is ``None`` (uncategorised, not a category); the literal
    ``"-"`` placeholder **is** a category, as it is upstream.
    """
    raw: str = observation.reason_raw.strip()
    if not raw:
        return None
    return raw.split(" - ", 1)[0].strip()


def _select(
    session: Session, scope: dict[str, Any]
) -> tuple[tuple[CanonicalPregameObservation, ...], dict[int, date]]:
    """The manifest's own selection, reproduced exactly.

    ``cohort_evidence.build_cohort_evidence`` selects over ``ready`` **only**,
    while its ``in_scope`` is ``[*ready, *missing_tipoff]``. That distinction is
    load-bearing and is reproduced here deliberately: selecting over ``in_scope``
    yields a larger, differently-defined population that will not reconcile with
    the committed marginals. See the backlog item
    ``cohort-canonical-count-reconciliation``, which exists because two
    artifacts disagree by 30 observations and this is the leading candidate.
    """
    ready, _missing_tipoff = games_to_backfill(
        session,
        season=scope["season"],
        season_type=SeasonType(scope["season_type"]),
        start=date.fromisoformat(scope["start_game_date"]),
        end=date.fromisoformat(scope["end_game_date"]),
    )
    observations = select_canonical_pregame_observations(
        session, game_ids=[game.game_id for game in ready]
    )
    return observations, {game.game_id: game.game_date for game in ready}


def _assert_marginals(
    observations: Sequence[CanonicalPregameObservation], manifest: dict[str, Any]
) -> None:
    """Refuse before printing if the selection does not reproduce.

    Both marginals, not one. ``status_counts`` alone would pass a selection that
    had the right rows with mangled reason text, and the reason cross is the
    table this script exists for.
    """
    checks = (
        (
            "canonical_observations.status_counts",
            dict(Counter(obs.status.value for obs in observations)),
            dict(manifest["canonical_observations"]["status_counts"]),
        ),
        (
            "reason_evidence.stated_reason_categories",
            dict(Counter(head for head in map(_reason_head, observations) if head is not None)),
            dict(manifest["reason_evidence"]["stated_reason_categories"]),
        ),
    )
    failures = []
    for name, computed, published in checks:
        if computed != published:
            failures.append((name, computed, published))
    if not failures:
        return
    lines = [
        "the selection does not reproduce the committed manifest, so every cross "
        "below it would be uncheckable evidence. Refusing.",
        "",
    ]
    for name, computed, published in failures:
        keys = sorted(set(computed) | set(published))
        lines.append(f"  {name}")
        lines.append(f"    {'key':<40} {'computed':>10} {'published':>10}")
        for key in keys:
            c, p = computed.get(key, 0), published.get(key, 0)
            flag = "" if c == p else "   <-- differs"
            lines.append(f"    {key:<40} {c:>10} {p:>10}{flag}")
        lines.append(
            f"    {'TOTAL':<40} {sum(computed.values()):>10} {sum(published.values()):>10}"
        )
        lines.append("")
    raise Refusal("\n".join(lines))


def _render(
    title: str,
    note: str,
    rows: Sequence[str],
    columns: Sequence[str],
    table: dict[str, Counter[str]],
    row_label: str,
) -> str:
    width = max([len(row_label), *(len(r) for r in rows)]) + 2
    out = [f"### {title}", "", note, ""]
    header = f"{row_label:<{width}}" + "".join(f"{c:>14}" for c in (*columns, "total"))
    out.append(header)
    out.append("-" * len(header))
    totals: Counter[str] = Counter()
    for row in rows:
        counts = table.get(row, Counter())
        line = f"{row:<{width}}"
        for column in columns:
            line += f"{counts.get(column, 0):>14}"
            totals[column] += counts.get(column, 0)
        line += f"{sum(counts.values()):>14}"
        out.append(line)
    out.append("-" * len(header))
    footer = f"{'total':<{width}}"
    for column in columns:
        footer += f"{totals[column]:>14}"
    footer += f"{sum(totals.values()):>14}"
    out.append(footer)
    return "\n".join(out)


def _reason_by_status(
    observations: Sequence[CanonicalPregameObservation],
) -> tuple[dict[str, Counter[str]], list[str]]:
    table: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for obs in observations:
        head = _reason_head(obs)
        if head is None:
            continue
        table[head][obs.status.value] += 1
    rows = sorted(table, key=lambda head: (-sum(table[head].values()), head))
    return dict(table), rows


def _era_by_band(
    observations: Sequence[CanonicalPregameObservation],
) -> dict[str, Counter[str]]:
    table: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for obs in observations:
        table[report_era(obs.report_timestamp)][lead_time_band(obs.lead_time_minutes)] += 1
    return dict(table)


def _partition_by_status(
    observations: Sequence[CanonicalPregameObservation], game_dates: dict[int, date]
) -> tuple[dict[str, Counter[str]], dict[str, tuple[date, date] | None], dict[str, Counter[str]]]:
    development, selection, held_out = chronological_split(
        sorted({game_dates[obs.game_id] for obs in observations})
    )
    membership = {
        "development": set(development),
        "selection": set(selection),
        "held_out": set(held_out),
    }
    table: defaultdict[str, Counter[str]] = defaultdict(Counter)
    doubtful_reasons: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for obs in observations:
        day = game_dates[obs.game_id]
        for name, days in membership.items():
            if day in days:
                table[name][obs.status.value] += 1
                if obs.status.value == "doubtful":
                    doubtful_reasons[name][_reason_head(obs) or "(no reason text)"] += 1
                break
    ranges = {name: ((min(days), max(days)) if days else None) for name, days in membership.items()}
    return dict(table), ranges, dict(doubtful_reasons)


def _doubtful_note(table: dict[str, Counter[str]]) -> str:
    """The one derived figure this prints, with its arithmetic beside it."""
    total = sum(counts.get("doubtful", 0) for counts in table.values())
    g_league = table.get("G League", Counter()).get("doubtful", 0)
    if not total:
        return "No doubtful observations; the G League share is undefined rather than zero."
    share = 100.0 * g_league / total
    return (
        f"{g_league} of {total} doubtful observations are G League - {share:.1f}%. "
        "A Two-Way player who might be recalled is real uncertainty and a roster "
        "mechanic, not a health event, so its conversion rate has no reason to "
        "resemble injury-doubtful. This is whole-cohort; the held-out figure that "
        "the >=30 activation floor is actually read against is a subset of it."
    )


def _held_out_direct_doubtful(
    path: Path, computed_range: tuple[date, date] | None
) -> tuple[int | None, str | None]:
    """The committed held-out direct ``doubtful`` count, or a reason there is none.

    **The partition check is the point of this function.** The bound below
    combines a canonical count computed here against a direct count published
    there, and the subset relation it rests on only holds if both describe the
    *same* held-out range. Nothing forces that: section 4's 50/25/25 boundaries
    are ``quant``'s parameter and may move, and if they move the two halves come
    from different partitions while every individual number stays perfectly
    valid. That is the failure this repository keeps finding - two well-formed
    quantities that are not about the same thing - so it is checked rather than
    assumed, and a mismatch withholds the bound instead of printing a wrong one.
    """
    if not path.is_file():
        return None, f"no admissibility artifact at {path}"
    section = json.loads(path.read_text(encoding="utf-8"))["section_2_admissibility"]
    if computed_range is None:
        return None, "no held-out observations were computed"
    published = (
        date.fromisoformat(section["held_out_start"]),
        date.fromisoformat(section["held_out_end"]),
    )
    if published != computed_range:
        return None, (
            f"the artifact's held-out range {published[0]}..{published[1]} is not the "
            f"one computed here, {computed_range[0]}..{computed_range[1]}. The subset "
            f"relation the bound rests on needs both halves to describe the same "
            f"partition, so no bound is offered. Two artifacts partitioned "
            f"differently is a finding"
        )
    count: int = section["held_out_direct_outcomes_by_status"]["doubtful"]
    return count, None


def _held_out_doubtful_note(
    reasons: Counter[str],
    held_out_direct_doubtful: int | None,
    bound_refusal: str | None,
) -> str:
    """Held-out ``doubtful`` split by stated reason, plus a bound on the fitted count.

    This is the closest checkable relative of the reviewer's ``83 -> ~74``
    claim, and the split itself is deliberately **not** that number. Their 83 is
    the held-out **direct** count; direct-ness is defined by membership of a
    participation outcome, so splitting *that* by reason would read outcomes.
    This splits the held-out **canonical** count - report designations only.

    The bound at the end is the payoff, and it needs nothing under the blind.
    Direct observations are a subset of canonical ones, so the number of
    canonical held-out ``doubtful`` rows that are *not* direct is just the
    difference of two already-committed integers. Every non-direct row is either
    G League or not, which brackets the health-reason direct count between two
    consecutive values without anyone joining anything. It converts a figure the
    reviewer had to assert on their own authority into one with arithmetic
    behind it.
    """
    total = sum(reasons.values())
    if not total:
        return "No held-out doubtful observations."
    g_league = reasons.get("G League", 0)
    health = total - g_league
    lines = [f"held-out doubtful by stated reason (canonical, total {total}):"]
    for head, count in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {head:<40} {count:>6}")
    lines.append(
        f"  -> {health} of {total} are non-G-League. This is CANONICAL; the >=30 "
        f"activation floor is read against the DIRECT count, a subset of it."
    )
    if held_out_direct_doubtful is None:
        lines.append(f"  -> no bound on the direct health-reason count: {bound_refusal}.")
        return "\n".join(lines)
    non_direct = total - held_out_direct_doubtful
    if non_direct < 0:
        lines.append(
            f"  -> REFUSING TO BOUND: the committed direct count "
            f"({held_out_direct_doubtful}) exceeds the canonical count ({total}), "
            f"which is impossible since direct is a subset. Two artifacts disagree; "
            f"that is a finding, not a rounding error."
        )
        return "\n".join(lines)
    lower = max(health - non_direct, 0)
    lines.append(
        f"  -> committed held-out DIRECT doubtful is {held_out_direct_doubtful}, so "
        f"exactly {non_direct} canonical row(s) are not direct. Each is G League or "
        f"not, so health-reason direct doubtful is in [{lower}, {health}] against a "
        f"floor of 30 - between {lower / 30:.2f}x and {health / 30:.2f}x, not the "
        f"{held_out_direct_doubtful / 30:.2f}x the unsplit count suggests. Derived "
        f"from two committed integers and a subset relation; no join, no outcome."
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", help="Path to the merged cohort SQLite store.")
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Committed cohort manifest the selection is asserted against.",
    )
    parser.add_argument(
        "--admissibility",
        default=str(DEFAULT_ADMISSIBILITY),
        help=(
            "Committed admissibility artifact, read only for its already-published "
            "held-out direct counts, to bound the health-reason doubtful figure."
        ),
    )
    args = parser.parse_args(argv)

    try:
        manifest = _load_manifest(Path(args.manifest))
        store = _store_path(args)
        engine = read_only_engine(store)
        with Session(engine) as session:
            observations, game_dates = _select(session, manifest["scope"])
        _assert_marginals(observations, manifest)
    except Refusal as refusal:
        print(f"REFUSED: {refusal}", file=sys.stderr)
        return 2
    except FileNotFoundError as missing:
        print(f"REFUSED: {missing}", file=sys.stderr)
        return 2

    print(f"store:    {store}")
    print(f"manifest: {Path(args.manifest).relative_to(REPO)}")
    print(
        f"selection reproduces both published marginals over "
        f"{len(observations)} canonical observations."
    )
    print()

    reason_table, reason_rows = _reason_by_status(observations)
    print(
        _render(
            "reason x status (canonical)",
            "Report designations only. No participation outcome is read.",
            reason_rows,
            STATUS_ORDER,
            reason_table,
            "stated reason",
        )
    )
    print()
    print(_doubtful_note(reason_table))
    print()

    era_table = _era_by_band(observations)
    bands = [name for name, _lo, _hi in LEAD_TIME_BANDS]
    era_rows = [row for row in ("legacy_hourly", "short_lead_fifteen_minute") if row in era_table]
    print(
        _render(
            "era x lead-time band (canonical)",
            "Era is classified from the report's own timestamp, never the game date.",
            era_rows,
            bands,
            era_table,
            "report era",
        )
    )
    print()

    partition_table, ranges, held_out_doubtful = _partition_by_status(observations, game_dates)
    print(
        _render(
            "partition x status (canonical)",
            "Section 4's 50/25/25 chronological split over distinct game dates. "
            "This is quant's parameter, applied here only to read an "
            "already-computed table.",
            PARTITIONS,
            STATUS_ORDER,
            partition_table,
            "partition",
        )
    )
    print()
    for name in PARTITIONS:
        span = ranges.get(name)
        print(f"  {name:<14} {span[0]}..{span[1]}" if span else f"  {name:<14} (empty)")
    print()
    held_out_direct_doubtful, bound_refusal = _held_out_direct_doubtful(
        Path(args.admissibility), ranges.get("held_out")
    )
    print(
        _held_out_doubtful_note(
            held_out_doubtful.get("held_out", Counter()),
            held_out_direct_doubtful,
            bound_refusal,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
