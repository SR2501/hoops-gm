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
    ["backend", "frontend", "migrations", "secrets", "postgres"],
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
