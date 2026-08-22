#!/usr/bin/env python3
"""Print each per-run number next to its previous value. Never judge it.

Runs in CI and is runnable locally:

    python scripts/run_metrics.py collect --label frontend \\
        --vitest frontend/vitest-report.json --root frontend --out metrics.json
    python scripts/run_metrics.py collect --label backend \\
        --junit backend/junit.xml --out metrics.json
    python scripts/run_metrics.py report --current metrics.json \\
        --baseline baseline/metrics.json --summary "$GITHUB_STEP_SUMMARY"

**Why this exists.** A frontend test's duration climbed 3,177 -> 3,309 -> 3,376
-> 3,714 -> 4,298 ms across CI runs and then blew a 5,000 ms timeout, turning an
assertion that never completed into a permanent green check. Vitest printed that
number, on its own line, above a summary that was quoted four separate times.
**Every individual value was unremarkable. Only the sequence was alarming, and
nothing computed the delta.**

**This is not a threshold and must never become one.** There is no budget here,
no assertion, no red build for a number that grew. A threshold recreates exactly
the guard that cries wolf the first time a number is legitimately allowed to
grow, and a guard that cries wolf is the one the next person deletes -- taking
the visibility with it. The report prints previous, current and delta, and stops
there. Reading it is a person's job.

**The one thing it does refuse.** ``collect`` exits non-zero when it parses zero
test cases. That is not judging a number; it is declining to write an empty
metrics file that ``report`` would later render as a serene table of nothing.
Seven checks in this repository on one day examined an empty set and reported
success, every one of them in the verification tool rather than the code, and a
metrics job that silently stopped matching its reporter's output would be the
next. Likewise ``report`` refuses a current file holding no metrics.

**Baselines come from the default branch, not from the previous run.** CI saves
the cache only on the default branch, so every branch compares against ``main``.
That is deliberate: run-to-run deltas for the climb above would have read +132,
+67, +338, +584 -- four unremarkable numbers, which is precisely the failure
being addressed. Against a fixed baseline the same climb reads as one
accumulating +1,121. A missing baseline prints "no baseline" and changes
nothing else.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCHEMA = 1
#: Sum of individual test durations, not the runner's wall-clock time. Wall
#: clock moves with runner parallelism and machine load, so it would swing by
#: tens of percent between identical commits -- and a column that is noise most
#: weeks trains its reader to skip the table, which is the same disease this
#: file exists to treat.
TOTAL_KEY = "suite.test_time_ms"
COUNT_KEY = "suite.tests"


@dataclass(frozen=True)
class Metric:
    key: str
    value: float
    unit: str


def _relative(path: str, root: Path) -> str:
    """Vitest reports absolute paths; a baseline keyed on one is worthless.

    ``/home/runner/work/hoops-gm/hoops-gm/frontend/src/x.test.tsx`` and the same
    file on a laptop share no key, so every test would read as added-and-removed
    on every run and no delta would ever be computed.
    """
    candidate = Path(path)
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return candidate.as_posix()


def collect_vitest(report: Path, root: Path) -> list[Metric]:
    payload: dict[str, Any] = json.loads(report.read_text(encoding="utf-8"))
    suites = payload.get("testResults") or []

    metrics: list[Metric] = []
    total = 0.0
    count = 0
    for suite in suites:
        relative = _relative(str(suite.get("name", "")), root)
        for case in suite.get("assertionResults") or []:
            name = case.get("fullName") or case.get("title") or "<unnamed>"
            duration = case.get("duration")
            count += 1
            if duration is None:  # skipped and todo tests carry no duration
                continue
            value = float(duration)
            total += value
            metrics.append(Metric(f"test.{relative}::{name}", round(value, 1), "ms"))

    # Counted from the elements actually present, never read off the report's
    # own `numTotalTests` summary: report the state observed, not the one
    # claimed. A reporter whose shape changed would keep a truthful-looking
    # count while yielding no cases at all.
    metrics.append(Metric(COUNT_KEY, float(count), "count"))
    metrics.append(Metric(TOTAL_KEY, round(total, 1), "ms"))
    return metrics


def collect_junit(report: Path) -> list[Metric]:
    root_element = ET.parse(report).getroot()
    cases = root_element.iter("testcase")

    metrics: list[Metric] = []
    total = 0.0
    count = 0
    for case in cases:
        classname = case.get("classname") or ""
        name = case.get("name") or "<unnamed>"
        count += 1
        raw = case.get("time")
        if raw is None:
            continue
        value = float(raw) * 1000.0  # junit reports seconds
        total += value
        label = f"{classname}::{name}" if classname else name
        metrics.append(Metric(f"test.{label}", round(value, 1), "ms"))

    metrics.append(Metric(COUNT_KEY, float(count), "count"))
    metrics.append(Metric(TOTAL_KEY, round(total, 1), "ms"))
    return metrics


def write_metrics(path: Path, label: str, metrics: Sequence[Metric]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "label": label,
        "metrics": [asdict(metric) for metric in metrics],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_metrics(path: Path) -> tuple[str, dict[str, Metric]]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    schema = payload.get("schema")
    if schema != SCHEMA:
        # A baseline written by an older layout is discarded rather than
        # half-read: a delta computed across two meanings of the same key is
        # worse than no delta, because it looks like information.
        raise ValueError(f"{path} has schema {schema!r}, expected {SCHEMA}")
    metrics = {
        str(entry["key"]): Metric(str(entry["key"]), float(entry["value"]), str(entry["unit"]))
        for entry in payload.get("metrics") or []
    }
    return str(payload.get("label", "")), metrics


def _format(value: float, unit: str) -> str:
    if unit == "count":
        return f"{value:,.0f}"
    return f"{value:,.1f}"


def _delta(previous: float | None, current: float, unit: str) -> str:
    if previous is None:
        return "n/a"
    difference = current - previous
    sign = "+" if difference >= 0 else ""
    if unit == "count":
        return f"{sign}{difference:,.0f}"
    percent = f" ({sign}{difference / previous * 100:.1f}%)" if previous else ""
    return f"{sign}{difference:,.1f}{percent}"


def render_report(
    label: str,
    current: dict[str, Metric],
    baseline: dict[str, Metric] | None,
    *,
    top: int,
) -> str:
    out: list[str] = [f"## Run metrics - {label}", ""]

    if baseline is None:
        out.append(
            "No baseline available, so no deltas below. A baseline is cached on the "
            "default branch; a first run on a new branch, an evicted cache or a "
            "changed metrics schema all land here. Nothing is wrong."
        )
        out.append("")

    out.append("### Totals")
    out.append("")
    out.append("| metric | previous | current | delta |")
    out.append("| --- | --- | --- | --- |")
    for key in (TOTAL_KEY, COUNT_KEY):
        entry = current.get(key)
        if entry is None:
            continue
        previous = baseline.get(key) if baseline else None
        previous_value = previous.value if previous else None
        out.append(
            f"| `{key}` | {_format(previous_value, entry.unit) if previous_value is not None else 'n/a'}"
            f" | {_format(entry.value, entry.unit)} | {_delta(previous_value, entry.value, entry.unit)} |"
        )
    out.append("")

    if baseline is not None:
        tests = {k: v for k, v in current.items() if k.startswith("test.")}
        base_tests = {k: v for k, v in baseline.items() if k.startswith("test.")}
        shared = sorted(
            (k for k in tests if k in base_tests),
            key=lambda k: abs(tests[k].value - base_tests[k].value),
            reverse=True,
        )
        moved = [k for k in shared if tests[k].value != base_tests[k].value][:top]

        out.append(f"### Individual tests that moved most (top {top})")
        out.append("")
        if moved:
            out.append("| test | previous | current | delta |")
            out.append("| --- | --- | --- | --- |")
            for key in moved:
                out.append(
                    f"| `{key.removeprefix('test.')}` | {_format(base_tests[key].value, 'ms')}"
                    f" | {_format(tests[key].value, 'ms')}"
                    f" | {_delta(base_tests[key].value, tests[key].value, 'ms')} |"
                )
        else:
            out.append("No test shared with the baseline changed duration.")
        out.append("")

        added = len(set(tests) - set(base_tests))
        removed = len(set(base_tests) - set(tests))
        out.append(f"{added} test(s) not in the baseline, {removed} in the baseline and not here.")
        out.append("")

    out.append(
        "_Printed, never asserted. No number here can fail a build, and none of them "
        "is compared against a budget._"
    )
    out.append("")
    return "\n".join(out)


def _cmd_collect(args: argparse.Namespace) -> int:
    if args.vitest:
        source: Path = args.vitest
        metrics = collect_vitest(source, args.root or source.parent)
    else:
        source = args.junit
        metrics = collect_junit(source)

    cases = [m for m in metrics if m.key.startswith("test.")]
    if not cases:
        print(
            f"error: parsed zero test cases from {source}. Either the run collected "
            "nothing or the reporter's format changed under this parser. Refusing to "
            "write a metrics file that would render as an empty table.",
            file=sys.stderr,
        )
        return 1

    write_metrics(args.out, args.label, metrics)
    print(f"{args.label}: collected {len(cases)} test durations from {source} -> {args.out}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    if not args.current.is_file():
        print(f"error: {args.current} does not exist", file=sys.stderr)
        return 1

    label, current = read_metrics(args.current)
    if not current:
        print(f"error: {args.current} holds no metrics", file=sys.stderr)
        return 1

    baseline: dict[str, Metric] | None = None
    if args.baseline and args.baseline.is_file():
        try:
            _, baseline = read_metrics(args.baseline)
        except (ValueError, json.JSONDecodeError, KeyError) as error:
            # An unreadable baseline is a missing baseline. It must never be the
            # reason a build goes red: this whole unit is print-only.
            print(f"note: ignoring unusable baseline {args.baseline}: {error}", file=sys.stderr)
            baseline = None

    report = render_report(label or args.label, current, baseline, top=args.top)
    print(report)
    sys.stdout.flush()
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    return 0


def _safe_stdout() -> None:
    """Test names carry characters this script does not control.

    One real name in this repository contains a multiplication sign. Printed
    through a cp1252 Windows console that is a ``UnicodeEncodeError``, which
    would turn a print-only report into a failing step -- the one outcome this
    unit must never produce. ``backslashreplace`` degrades to a visible escape
    rather than crashing or silently dropping the character.
    """
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    _safe_stdout()
    parser = argparse.ArgumentParser(
        description="Collect per-run test durations and print each against its baseline."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="read a test report into a metrics file")
    collect.add_argument("--label", required=True, help="e.g. frontend, backend")
    group = collect.add_mutually_exclusive_group(required=True)
    group.add_argument("--vitest", type=Path, help="vitest --reporter=json output")
    group.add_argument("--junit", type=Path, help="pytest --junitxml output")
    collect.add_argument("--root", type=Path, default=None, help="root for relative test paths")
    collect.add_argument("--out", type=Path, required=True)
    collect.set_defaults(func=_cmd_collect)

    report = sub.add_parser("report", help="print current metrics against a baseline")
    report.add_argument("--current", type=Path, required=True)
    report.add_argument("--baseline", type=Path, default=None)
    report.add_argument("--summary", type=Path, default=None, help="e.g. $GITHUB_STEP_SUMMARY")
    report.add_argument("--label", default="", help="used only if the metrics file has none")
    report.add_argument("--top", type=int, default=15)
    report.set_defaults(func=_cmd_report)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
