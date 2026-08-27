"""`scripts/check_ci_gates.py`: the fields that cannot lie, and the ones that can.

**Why this file exists.** On 2026-08-26 three GitHub summary fields were each
read as a result and each was wrong: `mergeStateStatus=CLEAN` on a pull request
with zero checks on its head, `conclusion=failure` on a run where no job was ever
assigned a runner, and `conclusion=cancelled` on a run with six jobs green and
zero failed steps. The script under test reports the honest fields instead. These
tests pin the three behaviours that make it honest rather than merely different.

**Every one was driven red before being trusted.** A verification tool whose own
tests have not been seen to fail is a verification tool with no evidence, which
is the argument the tool itself is built on.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_ci_gates.py"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_ci_gates", _SCRIPT)
    assert spec and spec.loader, f"cannot load {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(id_: int, name: str = "CI", conclusion: str = "success") -> dict[str, Any]:
    return {
        "id": id_,
        "name": name,
        "event": "push",
        "run_attempt": 1,
        "status": "completed",
        "conclusion": conclusion,
    }


def _job(
    name: str, conclusion: str, *, runner: str | None, failed_steps: int = 0
) -> dict[str, Any]:
    steps = [{"conclusion": "success"} for _ in range(3)]
    for index in range(failed_steps):
        steps[index] = {"conclusion": "failure"}
    return {"name": name, "conclusion": conclusion, "runner_name": runner, "steps": steps}


# --- the refusal, which must happen before any query --------------------------


def test_a_short_sha_is_refused_rather_than_queried(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The trap that nearly produced "no CI runs exist anywhere".

    `GET /actions/runs?head_sha=` returns an **empty set** for a short SHA and
    says nothing about it. Querying and reporting the zero would be a confident,
    reproducible-sounding falsehood, so the refusal happens first - asserted by
    making any call to the API an error.
    """

    def _explode(path: str) -> Any:
        raise AssertionError(f"queried {path} with a short SHA instead of refusing")

    monkeypatch.setattr(checker, "gh_api", _explode)

    assert checker.main(["18adbab"]) == 2
    assert "not a full 40-hex SHA" in capsys.readouterr().err


# --- skipped versus starved, which a job count cannot distinguish -------------


def test_a_skipped_job_and_a_starved_job_are_told_apart(checker: ModuleType) -> None:
    """`jobsWithRunner=9/10` is ambiguous and was quoted all afternoon as evidence.

    `Adapter gate - live smoke` is skipped by design and has no runner. A job
    starved of a runner also has no runner. A run with one starved job and one
    skipped job reads identically to a clean one under a count.
    """
    assert checker.classify_job(_job("live smoke", "skipped", runner=None)) == "skipped"
    assert checker.classify_job(_job("backend", "failure", runner=None)) == "starved"
    assert checker.classify_job(_job("backend", "success", runner="gh-1")) == "success"


# --- a conclusion is not a result --------------------------------------------


def test_a_cancelled_run_with_no_failed_steps_passes(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The real run `32990888364`: 6 green, 4 cancelled by supersession, 0 failed steps.

    Read as a conclusion it is a non-green. Read as failed steps it is nothing
    at all - a queued run arriving late and superseding a dispatch.
    """
    jobs = [_job(f"gate {i}", "success", runner="gh-1") for i in range(6)]
    jobs += [_job(f"gate {i}", "cancelled", runner="gh-1") for i in range(6, 10)]

    def _api(path: str) -> Any:
        if "/jobs" in path:
            return {"jobs": jobs}
        return {"workflow_runs": [_run(1, conclusion="cancelled")]}

    monkeypatch.setattr(checker, "gh_api", _api)

    exit_code = checker.main(["a" * 40])
    out = capsys.readouterr().out

    assert exit_code == 0, "a cancelled run with no failed step is not a failure"
    assert "steps conclusion=failure : 0" in out
    assert "jobs STARVED of a runner : 0" in out


def test_a_starved_job_fails_even_though_no_step_failed(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half, and the reason a failed-step count alone is not enough.

    A job that never got a runner has no steps to fail. Counting only failed
    steps would call that clean, which is the evidence-free red read from the
    wrong end.
    """
    jobs = [_job("backend", "failure", runner=None)]

    def _api(path: str) -> Any:
        if "/jobs" in path:
            return {"jobs": jobs}
        return {"workflow_runs": [_run(1)]}

    monkeypatch.setattr(checker, "gh_api", _api)

    assert checker.main(["a" * 40]) == 1


# --- the positive control on the tool's own query -----------------------------


def test_an_absence_is_only_reported_once_the_query_is_shown_to_work(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A zero is a fact only after the same query has returned non-zero somewhere.

    Subject has no runs; the control on the default-branch head does. Only then
    is "its gates have never seen it" an honest sentence.
    """
    monkeypatch.setattr(checker, "default_branch_head", lambda: "b" * 40)

    def _api(path: str) -> Any:
        if f"head_sha={'b' * 40}" in path:
            return {"workflow_runs": [_run(9)]}
        return {"workflow_runs": []}

    monkeypatch.setattr(checker, "gh_api", _api)

    exit_code = checker.main(["a" * 40])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "POSITIVE CONTROL" in out
    assert "absence is real" in out


def test_an_empty_control_reports_a_broken_query_rather_than_an_absence(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The control's own failure case, without which the control proves nothing.

    If the control is empty too, the query is broken and the tool says so and
    exits 2 - rather than reporting that CI never ran, which is the same
    confident falsehood one level up. This is `predict_union.py` refusing an
    empty base, pointed at CI.
    """
    monkeypatch.setattr(checker, "default_branch_head", lambda: "b" * 40)
    monkeypatch.setattr(checker, "gh_api", lambda path: {"workflow_runs": []})

    exit_code = checker.main(["a" * 40])

    assert exit_code == 2, "an unusable query must not be reported as an absence"
    assert "QUERY is not working" in capsys.readouterr().err


def test_codeql_is_reported_but_not_counted_as_a_gate(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A PR with only CodeQL has zero gates on it, and that is the `CLEAN` trap.

    CodeQL registers as `PR #<n>`. Counting it would let a head with no `CI` run
    report a non-zero check count, which is exactly how a PR with no gates
    looked better than one being verified.
    """
    monkeypatch.setattr(checker, "default_branch_head", lambda: "b" * 40)

    def _api(path: str) -> Any:
        if f"head_sha={'b' * 40}" in path:
            return {"workflow_runs": [_run(9)]}
        return {"workflow_runs": [_run(5, name="PR #108")]}

    monkeypatch.setattr(checker, "gh_api", _api)

    exit_code = checker.main(["a" * 40])
    out = capsys.readouterr().out

    assert exit_code == 1, "a head with only CodeQL has not been gated"
    assert "(not a gate) PR #108" in out
