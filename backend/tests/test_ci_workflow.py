"""The CI workflow's own coherence.

CI is the thing that enforces every gate, and nothing was enforcing CI. The
live smoke job shipped gating on ``github.event_name == 'schedule'`` while the
workflow declared no ``schedule`` trigger, so the job could never run on the
event its own comment described as the point of it.

That is the same failure as the enum CHECK and the timezone type: something
written down, believed, and never executed. These tests execute it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW_EVENTS = frozenset(
    {"push", "pull_request", "workflow_dispatch", "schedule", "workflow_call"}
)


@pytest.fixture
def workflow(repo_root: Path) -> dict[Any, Any]:
    path = repo_root / ".github" / "workflows" / "ci.yml"
    assert path.is_file(), "the Code gate is enforced by this file; it must exist"
    loaded: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture
def triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML parses a bare `on:` key as the boolean True, not the string "on".
    raw = workflow[True] if True in workflow else workflow["on"]
    assert isinstance(raw, dict), "expected a mapping of trigger names"
    return raw


@pytest.fixture
def jobs(workflow: dict[Any, Any]) -> dict[str, Any]:
    loaded: dict[str, Any] = workflow["jobs"]
    return loaded


def test_no_job_gates_on_an_event_that_cannot_fire(
    jobs: dict[str, Any], triggers: dict[str, Any]
) -> None:
    """The defect this file exists for.

    A condition naming an event the workflow does not declare is dead, and it
    is dead silently — the job simply never appears, and the comment above it
    goes on claiming otherwise.
    """
    dead: list[str] = []
    for name, job in jobs.items():
        condition = str(job.get("if", ""))
        for event in WORKFLOW_EVENTS:
            if f"'{event}'" in condition and event not in triggers:
                dead.append(f"{name} gates on '{event}', which is not in on:")

    assert dead == []


def test_the_live_smoke_job_cannot_block_a_merge(jobs: dict[str, Any]) -> None:
    """Adapter gate: allowed to fail without blocking a merge.

    Enforced structurally — it does not run on the events a merge depends on —
    rather than with continue-on-error, which would also hide a real failure.
    """
    condition = str(jobs["live-smoke"].get("if", ""))

    assert "workflow_dispatch" in condition
    assert "schedule" in condition
    assert "'push'" not in condition
    assert "'pull_request'" not in condition


def test_the_live_smoke_job_fails_loudly(jobs: dict[str, Any]) -> None:
    """ "Loudly and visibly" and continue-on-error are opposites.

    continue-on-error paints a real upstream break green on a nightly run
    nobody is watching, which is precisely the silent degradation the Adapter
    gate exists to prevent.
    """
    assert "continue-on-error" not in jobs["live-smoke"]


def test_the_code_gate_runs_on_push_and_pull_request(triggers: dict[str, Any]) -> None:
    assert "push" in triggers
    assert "pull_request" in triggers


@pytest.mark.parametrize(
    "job_name",
    ["backend", "frontend", "migrations", "secrets", "postgres", "backlog-graph"],
)
def test_code_gate_jobs_are_not_conditional(jobs: dict[str, Any], job_name: str) -> None:
    """A gate with an ``if`` is a gate someone can arrange not to run."""
    assert job_name in jobs, f"{job_name} job is missing from CI"
    assert "if" not in jobs[job_name]
    assert "continue-on-error" not in jobs[job_name]


@pytest.mark.parametrize(
    "job_name,marker",
    [
        ("adapter-gate", "adapter_contract"),
        ("live-smoke", "live_smoke"),
        ("model-gate", "model_backtest"),
    ],
)
def test_the_later_gates_select_registered_markers(
    jobs: dict[str, Any], job_name: str, marker: str
) -> None:
    """The extension points must stay wired to the markers they claim.

    ``--strict-markers`` means a renamed marker fails the run rather than
    silently selecting nothing, but only if the job still references it.
    """
    steps = jobs[job_name]["steps"]
    commands = " ".join(str(step.get("run", "")) for step in steps)

    assert f"pytest -m {marker}" in commands


def test_the_postgres_job_uses_a_password_that_needs_url_encoding(
    jobs: dict[str, Any],
) -> None:
    """Regression cover for the ConfigParser interpolation crash.

    A '%' in the connection URL used to break ``alembic upgrade head``. The
    Postgres job only proves that is fixed if its password actually contains
    the characters that trigger it.
    """
    url = str(jobs["postgres"]["env"]["TEST_DATABASE_URL"])

    assert "%25" in url, "no percent-encoded '%' in the CI database URL"


# --- The backlog dependency graph job ------------------------------------


def test_the_backlog_graph_job_actually_runs_the_checker(jobs: dict[str, Any]) -> None:
    """A job named for a check is not a check.

    The dangling edge this job exists to catch (`injury-report-backfill`, an
    item that does not exist) survived in the file for as long as it did
    because every reader assumed something was resolving those tokens.
    """
    steps = jobs["backlog-graph"]["steps"]
    assert steps, "backlog-graph declares no steps"
    commands = " ".join(str(step.get("run", "")) for step in steps)

    assert "scripts/backlog_graph.py" in commands


def test_the_backlog_graph_job_writes_to_the_step_summary(jobs: dict[str, Any]) -> None:
    """A number in a green job's log is a number nobody reads.

    That is the whole lesson of the duration climb: vitest printed it every
    run, above the summary a human quoted four separate times.
    """
    steps = jobs["backlog-graph"]["steps"]
    commands = " ".join(str(step.get("run", "")) for step in steps)

    assert "GITHUB_STEP_SUMMARY" in commands


# --- `scripts/` coverage --------------------------------------------------
#
# `scripts/` holds the tools this project uses to catch its own defects, and
# until this commit they were type-checked by `backend/pyproject.toml`
# (`files = ["src", "tests", "../scripts"]`, deliberately), executed only where
# a lane happened to put a test in `backend/tests/`, and **linted by nothing** —
# because `ruff check .` in the backend job runs with
# `working-directory: backend` and never reaches `../scripts`.
#
# These tests pin the two steps that close it. A CI step is deletable in one
# line and its absence is invisible in a green run, which is the same shape as
# the deleted test function that `scripts/test_name_diff.py` exists for.


def _run_lines(jobs: dict[str, Any], job_name: str) -> str:
    return " ".join(str(step.get("run", "")) for step in _steps(jobs, job_name))


def _commands(step: dict[str, Any]) -> list[str]:
    """The non-blank command lines of a step, stripped."""
    return [line.strip() for line in str(step.get("run", "")).splitlines() if line.strip()]


#: The exact command bodies the two `scripts/` gates must run.
#:
#: **Exact, not starts-with, and this is the third version of these tests.**
#: Version one matched substrings, so `echo "ruff check scripts"` passed.
#: Version two required a line to *start with* the executable, and a reviewer
#: walked through it with `ruff check scripts --help`, `... || true` and
#: `--exit-zero` - each starts correctly and checks nothing. Enumerating no-op
#: suffixes is the same losing game as enumerating syntactic forms, so the
#: command is pinned outright. Changing it is meant to cost an edit here.
_SCRIPTS_RUFF_COMMANDS = ["ruff check scripts", "ruff format --check scripts"]
_SCRIPTS_ESLINT_COMMANDS = ["../frontend/node_modules/.bin/eslint ."]
_DOC_TERMINATOR_COMMANDS = ["python scripts/check_doc_terminators.py"]


def _assert_step_is_live(step: dict[str, Any], what: str) -> None:
    """A step can be neutered without touching its command.

    ``if: ${{ false }}`` skips it, ``continue-on-error: true`` paints its
    failure green, and a custom ``shell:`` can swallow the exit code
    (``bash {0}; exit 0``). A test that only reads ``run:`` sees none of them,
    and all three were walked through earlier versions of these tests. The job
    level is covered by ``test_code_gate_jobs_are_not_conditional``; this is the
    step level.
    """
    assert "if" not in step, f"{what} is conditional, so it is a gate that can be arranged away"
    assert not step.get("continue-on-error"), f"{what} is allowed to fail, so it gates nothing"
    assert "shell" not in step, (
        f"{what} overrides the shell; a custom shell can discard the exit code, "
        f"which makes the command's presence say nothing about whether it gates"
    )


def _steps_running_exactly(
    jobs: dict[str, Any], job_name: str, commands: list[str]
) -> list[dict[str, Any]]:
    """Steps whose command body is exactly ``commands``."""
    return [step for step in _steps(jobs, job_name) if _commands(step) == commands]


def test_the_backend_job_lints_scripts_and_not_only_backend(jobs: dict[str, Any]) -> None:
    """`ruff check .` from `backend` is not a claim about `scripts/`.

    The narrow, checkable version of the finding: `mypy` covers `../scripts`
    on purpose and `ruff` did not, so the harnesses several backlog items cite
    as their evidence sat outside the gate that evidence is for.
    """
    steps = _steps_running_exactly(jobs, "backend", _SCRIPTS_RUFF_COMMANDS)

    assert steps, (
        "the backend job must run exactly "
        f"{_SCRIPTS_RUFF_COMMANDS}; `ruff check .` with "
        "`working-directory: backend` has never reached `scripts/`, and a "
        "command with anything appended is not this gate"
    )
    for step in steps:
        _assert_step_is_live(step, "the scripts lint step")


def test_the_scripts_lint_step_runs_from_the_repo_root(jobs: dict[str, Any]) -> None:
    """The working directory is the load-bearing part, not the command.

    `ruff check ../scripts` from `backend` picks up the backend rule set only
    because ruff falls back to the configuration discovered from the current
    working directory. Run from the repo root, `ruff.toml` is the config by
    ancestry instead — so this asserts the directory, which is the thing that
    would silently change the rules if someone "tidied" the step.
    """
    steps = _steps_running_exactly(jobs, "backend", _SCRIPTS_RUFF_COMMANDS)
    assert steps, "no backend step lints scripts/"

    for step in steps:
        assert "workspace" in str(step.get("working-directory", "")), (
            "the scripts lint step must override the job's `backend` working "
            "directory to the repo root; otherwise `scripts` does not resolve"
        )


def test_the_two_javascript_probes_are_linted_by_some_job(jobs: dict[str, Any]) -> None:
    """`browser_probe.mjs` and `reliability_probe.js` were covered by no gate.

    Not the frontend job, which lints `frontend/`; not the backend job, whose
    tools are Python. Searched across every job rather than pinned to one, so
    moving the step somewhere sensible does not fail this — but the command and
    the directory are both exact, because a step that merely mentions eslint is
    what the two previous versions of this test accepted.
    """
    found = [
        (job_name, step)
        for job_name, job in jobs.items()
        for step in job.get("steps", [])
        if _commands(step) == _SCRIPTS_ESLINT_COMMANDS
    ]

    assert found, (
        f"no job runs exactly {_SCRIPTS_ESLINT_COMMANDS}; the JavaScript in "
        "scripts/ is then linted by nothing"
    )
    for job_name, step in found:
        _assert_step_is_live(step, f"the scripts eslint step in `{job_name}`")
        assert str(step.get("working-directory", "")).endswith("scripts"), (
            "eslint must run from `scripts/`, because flat config resolves its "
            "`files` patterns relative to the config's base directory"
        )


def test_the_append_only_docs_are_checked_for_a_trailing_newline(jobs: dict[str, Any]) -> None:
    """A job deletable in one line, whose absence is invisible in a green run.

    `docs/handoff.md` lost its trailing newline twice on 2026-08-26. Without
    one, an appended `## YYYY-MM-DD` heading is welded onto the last line, so
    `predict_union.py` does not count it and the diff looks entirely normal -
    the entry is present and uncountable.

    **The owning job is checked as well as the step, and that is not
    belt-and-braces.** `test_code_gate_jobs_are_not_conditional` enumerates job
    names in a literal list, so a job added later is unprotected by it until
    somebody remembers - and `if: ${{ false }}` on the job disables the step
    without touching it. Driven: with only the step checked, that mutation
    escaped. Asserting the job that *actually contains* the command needs no
    list and cannot fall behind one.
    """
    found = [
        (job_name, step)
        for job_name, job in jobs.items()
        for step in job.get("steps", [])
        if _commands(step) == _DOC_TERMINATOR_COMMANDS
    ]

    assert found, (
        f"no job runs exactly {_DOC_TERMINATOR_COMMANDS}; an appended handoff "
        f"entry can then be silently uncountable"
    )
    for job_name, step in found:
        _assert_step_is_live(step, f"the doc-terminator step in `{job_name}`")
        job = jobs[job_name]
        assert "if" not in job, (
            f"job `{job_name}` is conditional, so its steps can be arranged not "
            f"to run without anyone editing them"
        )
        assert not job.get("continue-on-error"), f"job `{job_name}` is allowed to fail"


# --- Per-run metrics -----------------------------------------------------

METRIC_JOBS = ["backend", "frontend"]


def _steps(jobs: dict[str, Any], job_name: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = jobs[job_name]["steps"]
    assert steps, f"{job_name} declares no steps"
    return steps


def _metrics_commands(jobs: dict[str, Any], job_name: str) -> str:
    """Every ``run:`` line in the job that invokes the metrics script.

    Asserts it found some, because a helper that silently returns an empty
    string turns every caller into a test that passes over nothing.
    """
    found = [
        str(step["run"])
        for step in _steps(jobs, job_name)
        if "run_metrics.py" in str(step.get("run", ""))
    ]
    assert found, f"{job_name} never invokes run_metrics.py"
    return " ".join(found)


@pytest.mark.parametrize("job_name", METRIC_JOBS)
def test_the_metrics_steps_both_collect_and_report(jobs: dict[str, Any], job_name: str) -> None:
    """Collecting without reporting is a file nobody looks at."""
    commands = _metrics_commands(jobs, job_name)

    assert "run_metrics.py collect" in commands
    assert "run_metrics.py report" in commands


@pytest.mark.parametrize("job_name", METRIC_JOBS)
def test_the_report_reads_the_file_the_collector_wrote(jobs: dict[str, Any], job_name: str) -> None:
    """Two paths written six lines apart are two paths that can drift.

    If they drift, ``report`` reads a file that is not there, treats it as a
    missing baseline, and prints a serene table of first-ever numbers on every
    run forever. Nothing goes red.
    """
    commands = _metrics_commands(jobs, job_name)
    out = _flag_value(commands, "--out")
    current = _flag_value(commands, "--current")

    assert out == current, f"collect writes {out!r} but report reads {current!r}"


@pytest.mark.parametrize("job_name", METRIC_JOBS)
def test_the_baseline_path_is_the_directory_that_is_cached(
    jobs: dict[str, Any], job_name: str
) -> None:
    """The cached directory and the ``--baseline`` file must agree.

    The cache action's ``path`` is relative to the workspace; the script's
    arguments are relative to the job's working directory. Getting that
    mismatched restores a real baseline into a place nothing reads.
    """
    commands = _metrics_commands(jobs, job_name)
    baseline = _flag_value(commands, "--baseline")

    cached = [
        str(step["with"]["path"])
        for step in _steps(jobs, job_name)
        if str(step.get("uses", "")).startswith("actions/cache")
    ]
    assert cached, f"{job_name} caches nothing, so no run can ever have a baseline"

    working_dir = jobs[job_name]["defaults"]["run"]["working-directory"]
    for path in cached:
        assert path == f"{working_dir}/{baseline.split('/')[0]}"


@pytest.mark.parametrize("job_name", METRIC_JOBS)
def test_the_baseline_is_only_saved_on_the_default_branch(
    jobs: dict[str, Any], job_name: str
) -> None:
    """Every branch must compare against main, not against itself.

    The motivating climb was 3,177 -> 3,309 -> 3,376 -> 3,714 -> 4,298 ms. As
    run-to-run deltas that is +132, +67, +338, +584: four numbers nobody would
    act on. Against a fixed baseline it is one +1,121.

    If a branch saved its own baseline it would re-anchor every run, and the
    tool would print the forgettable version of the exact sequence it was
    built to make visible.
    """
    saving = [
        step
        for step in _steps(jobs, job_name)
        if str(step.get("uses", "")).startswith("actions/cache/save")
        or (
            "metrics-baseline" in str(step.get("run", ""))
            # The report step names the same directory to *read* it, and is
            # rightly unconditional. Only writers are in scope here.
            and "run_metrics.py" not in str(step.get("run", ""))
        )
    ]
    assert saving, f"{job_name} never saves a baseline, so no run can ever have one"

    for step in saving:
        condition = str(step.get("if", ""))
        assert "default_branch" in condition, (
            f"a step in {job_name} writes the baseline under {condition!r}, "
            "which is not restricted to the default branch"
        )


@pytest.mark.parametrize("job_name", METRIC_JOBS)
def test_restoring_the_baseline_is_not_restricted_to_the_default_branch(
    jobs: dict[str, Any], job_name: str
) -> None:
    """The mirror of the rule above, and easy to get backwards.

    Only main writes; everything reads. A conditional restore would leave
    branches -- where the change under review actually is -- with no
    comparison at all.
    """
    restoring = [
        step
        for step in _steps(jobs, job_name)
        if str(step.get("uses", "")).startswith("actions/cache/restore")
    ]
    assert restoring, f"{job_name} never restores a baseline"

    for step in restoring:
        assert "if" not in step


@pytest.mark.parametrize("job_name", METRIC_JOBS)
def test_the_metrics_steps_are_not_painted_green(jobs: dict[str, Any], job_name: str) -> None:
    """These steps have exactly one failure mode, and it is worth a red build.

    ``collect`` fails only when it parsed zero test cases -- meaning the
    reporter's format moved underneath it. A slow test cannot fail it. Adding
    ``continue-on-error`` would leave a broken collector publishing an empty
    table for months, which is this repository's most common defect: a check
    that examined an empty set and reported success.
    """
    for step in _steps(jobs, job_name):
        if "run_metrics.py" in str(step.get("run", "")):
            assert "continue-on-error" not in step


def test_the_backend_metrics_read_the_report_pytest_writes(jobs: dict[str, Any]) -> None:
    """``--junitxml`` in one step, ``--junit`` in another, nothing joining them."""
    steps = _steps(jobs, "backend")
    pytest_commands = [
        str(step["run"]) for step in steps if str(step.get("run", "")).startswith("pytest")
    ]
    assert pytest_commands, "the backend job does not run pytest"

    written = _flag_value(" ".join(pytest_commands), "--junitxml")
    read = _flag_value(_metrics_commands(jobs, "backend"), "--junit")

    assert written == read, f"pytest writes {written!r}, collect reads {read!r}"


def test_the_frontend_metrics_read_the_report_vitest_writes(jobs: dict[str, Any]) -> None:
    steps = _steps(jobs, "frontend")
    test_commands = [
        str(step["run"]) for step in steps if "--outputFile.json" in str(step.get("run", ""))
    ]
    assert test_commands, "the frontend job writes no vitest JSON report"

    written = _flag_value(" ".join(test_commands), "--outputFile.json")
    read = _flag_value(_metrics_commands(jobs, "frontend"), "--vitest")

    assert written == read, f"vitest writes {written!r}, collect reads {read!r}"


def test_the_frontend_keeps_a_readable_reporter(jobs: dict[str, Any]) -> None:
    """Collecting a duration must not cost the output a human reads on failure.

    ``--reporter=json`` alone replaces the console reporter, so a failing test
    would report as a machine-readable blob. The metric is worth less than
    knowing which test broke.
    """
    steps = _steps(jobs, "frontend")
    test_commands = [
        str(step["run"]) for step in steps if "--outputFile.json" in str(step.get("run", ""))
    ]
    assert test_commands, "the frontend job writes no vitest JSON report"

    for command in test_commands:
        assert "--reporter=default" in command


def _flag_value(command: str, flag: str) -> str:
    """Read ``--flag value`` or ``--flag=value`` out of a shell command.

    Asserts the flag is present rather than returning a default, so a renamed
    flag fails the test that uses it instead of comparing two empty strings
    and passing.
    """
    tokens = command.replace("\n", " ").split()
    for index, token in enumerate(tokens):
        if token == flag:
            assert index + 1 < len(tokens), f"{flag} has no value in {command!r}"
            return tokens[index + 1]
        if token.startswith(f"{flag}="):
            return token.split("=", 1)[1]
    raise AssertionError(f"{flag} not found in {command!r}")


def test_the_flag_reader_fails_on_a_flag_that_is_not_there() -> None:
    """The helper above is load-bearing for six tests; it must not return ''."""
    assert _flag_value("pytest --junitxml=junit.xml", "--junitxml") == "junit.xml"
    assert _flag_value("collect --junit junit.xml", "--junit") == "junit.xml"

    with pytest.raises(AssertionError):
        _flag_value("pytest --junitxml=junit.xml", "--vitest")
