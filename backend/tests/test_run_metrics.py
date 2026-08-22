"""Tests for ``scripts/run_metrics.py``.

The parsers here are written against two third-party report formats, so the
tests use **captured real output** in the shapes those reporters actually emit,
not a schema recalled from documentation. Both were generated on 2026-08-21 by
running the repository's own suites:

- vitest 3.2 ``--reporter=json``: a Jest-shaped payload whose ``testResults[].name``
  is an **absolute path**, and whose ``assertionResults[].duration`` is a float
  in milliseconds that is ``null`` for a skipped test.
- pytest ``--junitxml``: ``<testcase classname=... name=... time=...>`` where
  ``time`` is in **seconds**.

Two of those four details would silently corrupt every delta if got wrong, and
neither is visible from a green run: an absolute path makes every test look
added-and-removed on each run so no delta is ever computed, and seconds read as
milliseconds makes a 4.3-second test print as 4.3.

``test_collect_refuses_a_report_with_no_test_cases`` is the one that keeps the
rest honest. Everything else here would pass over an empty metrics file.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_metrics.py"


@pytest.fixture(scope="module")
def metrics() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_metrics", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- captured shapes ---------------------------------------------------------


def vitest_payload(root: Path) -> dict[str, Any]:
    """The shape vitest 3.2 really writes, including the absolute path."""
    return {
        "numTotalTests": 3,
        "success": True,
        "startTime": 1_700_000_000_000,
        "testResults": [
            {
                "name": str(root / "src" / "components" / "ProjectionsTable.test.tsx"),
                "status": "passed",
                "startTime": 1_700_000_000_000,
                "endTime": 1_700_000_004_298,
                "assertionResults": [
                    {
                        "ancestorTitles": [],
                        "fullName": "renders no rate \u00d7 assumed_games_played product",
                        "title": "renders no rate product",
                        "status": "passed",
                        "duration": 4298.0,
                        "failureMessages": [],
                    },
                    {
                        "ancestorTitles": [],
                        "fullName": "skipped one",
                        "title": "skipped one",
                        "status": "skipped",
                        "duration": None,
                        "failureMessages": [],
                    },
                ],
            },
            {
                "name": str(root / "src" / "api" / "client.test.ts"),
                "status": "passed",
                "startTime": 1_700_000_000_000,
                "endTime": 1_700_000_000_006,
                "assertionResults": [
                    {
                        "ancestorTitles": ["apiFetch"],
                        "fullName": "apiFetch returns the parsed body on success",
                        "title": "returns the parsed body on success",
                        "status": "passed",
                        "duration": 5.7,
                        "failureMessages": [],
                    }
                ],
            },
        ],
    }


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests"><testsuite name="pytest" errors="0" failures="0" skipped="0"
 tests="2" time="6.122" timestamp="2026-08-21T22:13:18" hostname="runner">
<testcase classname="tests.test_schedule" name="test_a_thing" time="4.970" />
<testcase classname="tests.test_api" name="test_another[case-1]" time="0.026" />
</testsuite></testsuites>
"""


@pytest.fixture
def vitest_report(tmp_path: Path) -> Path:
    root = tmp_path / "frontend"
    root.mkdir()
    path = root / "vitest-report.json"
    path.write_text(json.dumps(vitest_payload(root)), encoding="utf-8")
    return path


@pytest.fixture
def junit_report(tmp_path: Path) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(JUNIT, encoding="utf-8")
    return path


def by_key(collected: Any) -> dict[str, Any]:
    return {metric.key: metric for metric in collected}


# --- collecting --------------------------------------------------------------


def test_vitest_durations_are_read_in_milliseconds(
    metrics: ModuleType, vitest_report: Path
) -> None:
    collected = by_key(metrics.collect_vitest(vitest_report, vitest_report.parent))
    key = (
        "test.src/components/ProjectionsTable.test.tsx"
        "::renders no rate \u00d7 assumed_games_played product"
    )

    assert collected[key].value == pytest.approx(4298.0)
    assert collected[key].unit == "ms"


def test_vitest_paths_are_made_relative(metrics: ModuleType, vitest_report: Path) -> None:
    """An absolute path in a key makes every baseline useless.

    ``/home/runner/work/...`` and the same file on a laptop share no key, so
    every test reads as added-and-removed and no delta is ever computed --
    silently, with a full-looking table of "new" tests every run.
    """
    collected = by_key(metrics.collect_vitest(vitest_report, vitest_report.parent))
    test_keys = [k for k in collected if k.startswith("test.")]

    assert test_keys, "no test durations parsed at all"
    for key in test_keys:
        assert str(vitest_report.parent) not in key
        assert not key.removeprefix("test.").startswith("/")
        assert ":\\" not in key, f"a Windows drive letter survived into {key!r}"


def test_junit_seconds_become_milliseconds(metrics: ModuleType, junit_report: Path) -> None:
    """pytest reports seconds. Read as milliseconds, a 4.97s test prints as 4.97."""
    collected = by_key(metrics.collect_junit(junit_report))

    assert collected["test.tests.test_schedule::test_a_thing"].value == pytest.approx(4970.0)
    assert collected["test.tests.test_api::test_another[case-1]"].value == pytest.approx(26.0)


def test_the_total_is_the_sum_of_test_durations(metrics: ModuleType, junit_report: Path) -> None:
    collected = by_key(metrics.collect_junit(junit_report))

    assert collected[metrics.TOTAL_KEY].value == pytest.approx(4996.0)


def test_a_skipped_test_counts_but_adds_no_duration(
    metrics: ModuleType, vitest_report: Path
) -> None:
    """``duration`` is ``null`` for a skipped test; float(None) would raise."""
    collected = by_key(metrics.collect_vitest(vitest_report, vitest_report.parent))

    assert collected[metrics.COUNT_KEY].value == 3
    assert collected[metrics.TOTAL_KEY].value == pytest.approx(4303.7)


def test_the_count_is_observed_not_taken_from_the_reports_own_summary(
    metrics: ModuleType, tmp_path: Path
) -> None:
    """Report the state observed, never the parameter passed.

    A payload whose ``numTotalTests`` says 999 while it carries one case must
    report one. Trusting the summary field is how a reporter whose shape
    changed keeps publishing a confident, wrong number.
    """
    root = tmp_path / "frontend"
    root.mkdir()
    payload = vitest_payload(root)
    payload["numTotalTests"] = 999
    path = root / "report.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    collected = by_key(metrics.collect_vitest(path, root))

    assert collected[metrics.COUNT_KEY].value == 3


# --- the refusal, which every other test here depends on ---------------------


def test_collect_refuses_a_report_with_no_test_cases(metrics: ModuleType, tmp_path: Path) -> None:
    """A metrics file over an empty set would render as a serene empty table."""
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"numTotalTests": 0, "testResults": []}), encoding="utf-8")
    out = tmp_path / "metrics.json"

    assert (
        metrics.main(["collect", "--label", "frontend", "--vitest", str(path), "--out", str(out)])
        == 1
    )
    assert not out.exists(), "an empty metrics file was written anyway"


def test_collect_refuses_a_junit_file_with_no_cases(metrics: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "junit.xml"
    path.write_text(
        '<?xml version="1.0"?><testsuites><testsuite tests="0" /></testsuites>', encoding="utf-8"
    )
    out = tmp_path / "metrics.json"

    assert (
        metrics.main(["collect", "--label", "backend", "--junit", str(path), "--out", str(out)])
        == 1
    )


def test_report_refuses_a_metrics_file_holding_nothing(metrics: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"schema": 1, "label": "x", "metrics": []}), encoding="utf-8")

    assert metrics.main(["report", "--current", str(path)]) == 1


def test_report_refuses_a_missing_metrics_file(metrics: ModuleType, tmp_path: Path) -> None:
    assert metrics.main(["report", "--current", str(tmp_path / "absent.json")]) == 1


# --- round trip and reporting ------------------------------------------------


def test_collect_then_report_round_trips(
    metrics: ModuleType, junit_report: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "metrics.json"

    assert (
        metrics.main(
            ["collect", "--label", "backend", "--junit", str(junit_report), "--out", str(out)]
        )
        == 0
    )
    assert metrics.main(["report", "--current", str(out)]) == 0

    printed = capsys.readouterr().out
    assert "Run metrics - backend" in printed
    assert "4,996.0" in printed


def test_the_climb_that_motivated_this_is_visible_as_one_number(
    metrics: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The actual failure: 1,094 ms -> 4,298 ms, invisible one run at a time."""
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    metric = metrics.Metric
    key = "test.src/components/ProjectionsTable.recorded.test.tsx::absence markers"

    metrics.write_metrics(
        baseline,
        "frontend",
        [
            metric(key, 1094.0, "ms"),
            metric(metrics.TOTAL_KEY, 2439.0, "ms"),
            metric(metrics.COUNT_KEY, 194.0, "count"),
        ],
    )
    metrics.write_metrics(
        current,
        "frontend",
        [
            metric(key, 4298.0, "ms"),
            metric(metrics.TOTAL_KEY, 5643.0, "ms"),
            metric(metrics.COUNT_KEY, 194.0, "count"),
        ],
    )

    assert metrics.main(["report", "--current", str(current), "--baseline", str(baseline)]) == 0

    printed = capsys.readouterr().out
    assert "1,094.0" in printed
    assert "4,298.0" in printed
    assert "+3,204.0" in printed


@pytest.mark.parametrize("multiplier", [1.1, 2.0, 10.0, 100.0, 1000.0])
def test_no_magnitude_of_growth_makes_the_report_fail(
    metrics: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], multiplier: float
) -> None:
    """The binding constraint of this unit, asserted behaviourally.

    A threshold recreates the guard that cries wolf the first time a number is
    legitimately allowed to grow, and that guard is the one the next person
    deletes -- taking the visibility with it.

    Word-scanning the output for "budget" or "threshold" was the first version
    of this test and it was a weak proxy: it failed on the report's own
    disclaimer, and it would pass over a threshold phrased in any other words.
    Sweeping the magnitude is the real claim -- a limit set anywhere would be
    crossed at one of these points and not the ones below it.
    """
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    metric = metrics.Metric
    key = "test.a::b"
    metrics.write_metrics(
        baseline, "frontend", [metric(key, 100.0, "ms"), metric(metrics.TOTAL_KEY, 100.0, "ms")]
    )
    metrics.write_metrics(
        current,
        "frontend",
        [
            metric(key, 100.0 * multiplier, "ms"),
            metric(metrics.TOTAL_KEY, 100.0 * multiplier, "ms"),
        ],
    )

    assert metrics.main(["report", "--current", str(current), "--baseline", str(baseline)]) == 0

    printed = capsys.readouterr().out
    # The two ways a GitHub Actions step shouts at a reader. Neither may appear
    # however large the delta is.
    assert "::error" not in printed
    assert "::warning" not in printed


def test_the_report_says_plainly_that_it_asserts_nothing(
    metrics: ModuleType, junit_report: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "metrics.json"
    metrics.main(["collect", "--label", "backend", "--junit", str(junit_report), "--out", str(out)])
    capsys.readouterr()

    metrics.main(["report", "--current", str(out)])

    assert "Printed, never asserted" in capsys.readouterr().out


def test_a_missing_baseline_prints_a_report_anyway(
    metrics: ModuleType, junit_report: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cache eviction and a first run on a new branch both land here."""
    out = tmp_path / "metrics.json"
    metrics.main(["collect", "--label", "backend", "--junit", str(junit_report), "--out", str(out)])
    capsys.readouterr()

    assert (
        metrics.main(["report", "--current", str(out), "--baseline", str(tmp_path / "absent.json")])
        == 0
    )
    assert "No baseline available" in capsys.readouterr().out


def test_an_unreadable_baseline_is_treated_as_a_missing_one(
    metrics: ModuleType, junit_report: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A corrupt cache entry must never be the reason a build goes red."""
    out = tmp_path / "metrics.json"
    metrics.main(["collect", "--label", "backend", "--junit", str(junit_report), "--out", str(out)])
    bad = tmp_path / "bad.json"
    bad.write_text("{not json at all", encoding="utf-8")
    capsys.readouterr()

    assert metrics.main(["report", "--current", str(out), "--baseline", str(bad)]) == 0
    assert "No baseline available" in capsys.readouterr().out


def test_a_baseline_from_another_schema_is_discarded_not_half_read(
    metrics: ModuleType, junit_report: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A delta across two meanings of one key looks like information."""
    out = tmp_path / "metrics.json"
    metrics.main(["collect", "--label", "backend", "--junit", str(junit_report), "--out", str(out)])
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"schema": 0, "label": "backend", "metrics": []}), encoding="utf-8")
    capsys.readouterr()

    assert metrics.main(["report", "--current", str(out), "--baseline", str(old)]) == 0
    assert "No baseline available" in capsys.readouterr().out


def test_added_and_removed_tests_are_counted(
    metrics: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    metric = metrics.Metric
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    metrics.write_metrics(
        baseline, "f", [metric("test.a::x", 1.0, "ms"), metric("test.gone::y", 1.0, "ms")]
    )
    metrics.write_metrics(
        current, "f", [metric("test.a::x", 1.0, "ms"), metric("test.new::z", 1.0, "ms")]
    )

    metrics.main(["report", "--current", str(current), "--baseline", str(baseline)])

    assert (
        "1 test(s) not in the baseline, 1 in the baseline and not here." in capsys.readouterr().out
    )


def test_the_summary_file_is_appended_to_never_truncated(
    metrics: ModuleType, junit_report: Path, tmp_path: Path
) -> None:
    """$GITHUB_STEP_SUMMARY is shared with every other step in the job."""
    out = tmp_path / "metrics.json"
    metrics.main(["collect", "--label", "backend", "--junit", str(junit_report), "--out", str(out)])
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step output\n", encoding="utf-8")

    assert metrics.main(["report", "--current", str(out), "--summary", str(summary)]) == 0

    written = summary.read_text(encoding="utf-8")
    assert written.startswith("earlier step output\n")
    assert "Run metrics" in written


def test_a_non_ascii_test_name_survives_the_round_trip(
    metrics: ModuleType, vitest_report: Path, tmp_path: Path
) -> None:
    """One real frontend test name contains a multiplication sign.

    The metrics file is the thing keys are matched on, so it must hold the
    character exactly; only the console rendering is allowed to degrade.
    """
    out = tmp_path / "metrics.json"
    metrics.main(
        [
            "collect",
            "--label",
            "frontend",
            "--vitest",
            str(vitest_report),
            "--root",
            str(vitest_report.parent),
            "--out",
            str(out),
        ]
    )

    _, loaded = metrics.read_metrics(out)
    assert any("\u00d7" in key for key in loaded), "the multiplication sign was lost"
