"""Report what CI actually did on one exact commit, in the fields that cannot lie.

**Why this exists.** On 2026-08-26 three separate GitHub summary fields were each
read as a result and each was wrong:

* `mergeStateStatus=CLEAN` on a PR with **zero** checks on its head. A PR whose
  gates all passed and a PR whose gates never ran are indistinguishable by that
  field, and the one that never ran looks *better*, because a mid-run PR reports
  `UNSTABLE`.
* `conclusion=failure` on a run where **0 of 10 jobs were ever assigned a
  runner** and no step failed - an evidence-free red that cost a lane its queue
  position.
* `conclusion=cancelled` on a run with 6 jobs green, 4 cancelled mid-flight and
  **0 failed steps** - superseded by a queued run, which is nothing at all.

They are one defect: **a summary field is not a result**, and a summary computed
over an empty or partial set summarises beautifully. The honest fields are the
count of steps that actually failed, and the count of jobs that never got a
runner.

## The skipped/starved distinction, which is the whole point

`jobsWithRunner=9/10` was reported all afternoon as though it were evidence. It
is ambiguous: `Adapter gate - live smoke` is **skipped by design** and has no
runner, and a job **starved** of a runner also has no runner. A run with one
genuinely starved job and one skipped job reads identically to a clean one. This
prints the split rather than leaving it to be inferred.

## The positive control, which is not optional

`GET /actions/runs?head_sha=` **silently returns an empty set for a short SHA**.
A coordinator nearly published "no CI runs exist anywhere" on that. So a full
40-hex SHA is required outright, and an empty result for the subject is checked
against the same query run on the default branch's head: if that is *also*
empty, the query is broken and this says so, rather than reporting a zero.

**A statistic over nothing is not a small statistic, it is not a statistic.**
`scripts/predict_union.py` and the backlog census already refuse an empty base
rather than reporting zero; this is that pattern, pointed at CI.

## Usage

    python scripts/check_ci_gates.py <full-40-hex-sha>
    python scripts/check_ci_gates.py "$(git rev-parse HEAD)"
    python scripts/check_ci_gates.py "$(gh pr view 108 --json headRefOid -q .headRefOid)"

**Resolve the SHA from the pull request, never from a branch name you recall.**
A stale branch is not an empty result, it is a *plausible* one: on the day this
was written, a merged branch still on the remote resolved to a real SHA with a
real green CI run belonging to a different pull request entirely.

Exits 1 if any step failed, if any job was starved, or if no CI run exists for
the commit. Exits 2 if the arguments or the query itself are unusable.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

# **The console rule's other half.** `backend/tests/test_console_encoding.py`
# keeps this file's own string *literals* inside cp1252, which they are. But
# every gate name printed below arrives from the GitHub API, and this project's
# job names contain em dashes - `Backend - lint, type-check, tests` is really
# `Backend \u2014 lint...`. Those are not source literals, so that test cannot
# see them, and on the owner's Windows console they arrive as replacement marks.
# Driven rather than assumed: the first run of this script printed
# `Backend ? the same suite against Postgres`.
#
# `errors="replace"` as well as UTF-8, because a mangled gate name must never be
# the thing that turns a verdict into a `UnicodeEncodeError` - the same reason
# `mutate_calibration.py` sets `PYTHONIOENCODING` for its child.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = "SR2501/hoops-gm"

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

#: The workflow carrying the gates. CodeQL registers as `PR #<n>` and is not a
#: gate this project defines, so it is reported separately rather than counted.
GATE_WORKFLOW = "CI"


def gh_api(path: str) -> Any:
    proc = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, check=False, encoding="utf-8"
    )
    if proc.returncode != 0:
        print(f"gh api failed for {path}:\n{proc.stderr.strip()}", file=sys.stderr)
        raise SystemExit(2)
    return json.loads(proc.stdout)


def runs_for(sha: str) -> list[dict[str, Any]]:
    payload = gh_api(f"repos/{REPO}/actions/runs?head_sha={sha}&per_page=100")
    runs: list[dict[str, Any]] = payload.get("workflow_runs", [])
    return runs


def default_branch_head() -> str:
    repo = gh_api(f"repos/{REPO}")
    branch = gh_api(f"repos/{REPO}/branches/{repo['default_branch']}")
    head: str = branch["commit"]["sha"]
    return head


def classify_job(job: dict[str, Any]) -> str:
    """`skipped`, `starved`, or the job's own conclusion.

    A skipped job and a job that never got a runner both have no `runner_name`.
    They are told apart by the conclusion, and conflating them is what made
    `jobsWithRunner=9/10` unreadable.
    """
    conclusion = job.get("conclusion")
    if conclusion == "skipped":
        return "skipped"
    if not job.get("runner_name"):
        return "starved"
    return str(conclusion)


def report_run(run: dict[str, Any]) -> tuple[int, int]:
    """Print one run's gates. Returns (failed steps, starved jobs)."""
    jobs = gh_api(f"repos/{REPO}/actions/runs/{run['id']}/jobs?per_page=100").get("jobs", [])

    failed_steps = 0
    starved = 0
    skipped = 0
    for job in jobs:
        failed_steps += sum(
            1 for step in job.get("steps", []) if step.get("conclusion") == "failure"
        )
        state = classify_job(job)
        starved += state == "starved"
        skipped += state == "skipped"

    print(f"  run {run['id']}  event={run['event']}  attempt={run.get('run_attempt')}")
    print(f"    reported conclusion : {run['status']}/{run['conclusion']}   <- not a result")
    print(f"    gates (jobs)        : {len(jobs)}")
    print(f"    steps conclusion=failure : {failed_steps}")
    print(f"    jobs skipped by design   : {skipped}")
    print(f"    jobs STARVED of a runner : {starved}")
    if not jobs:
        print("    no jobs at all - this run establishes nothing about the commit")
    for job in jobs:
        print(f"      {classify_job(job):<9} {job['name']}")
    return failed_steps, starved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="What CI actually did on one exact commit.")
    parser.add_argument("sha", help="a FULL 40-hex commit SHA; short SHAs return empty silently")
    args = parser.parse_args(argv)

    if not FULL_SHA.match(args.sha):
        print(
            f"{args.sha!r} is not a full 40-hex SHA. The runs endpoint returns an "
            f"empty set for a short SHA without complaining, so a truncated one "
            f"produces a confident 'no runs exist'. Refusing rather than querying.",
            file=sys.stderr,
        )
        return 2

    runs = runs_for(args.sha)
    gates = [run for run in runs if run["name"] == GATE_WORKFLOW]
    other = [run for run in runs if run["name"] != GATE_WORKFLOW]

    print(f"commit {args.sha}")
    print(f"  workflow runs found: {len(runs)}  ({len(gates)} named {GATE_WORKFLOW!r})")
    for run in other:
        print(f"    (not a gate) {run['name']}  {run['status']}/{run['conclusion']}")

    if not gates:
        # A zero is only a fact once the query has been shown to work.
        control_sha = default_branch_head()
        control = [r for r in runs_for(control_sha) if r["name"] == GATE_WORKFLOW]
        print()
        print(f"  POSITIVE CONTROL on the same query, default-branch head {control_sha[:7]}:")
        print(f"    {len(control)} run(s) named {GATE_WORKFLOW!r}")
        if not control:
            print(
                "\n  The control is empty too, so the QUERY is not working and this "
                "says nothing about the commit. Do not read this as 'CI did not run'.",
                file=sys.stderr,
            )
            return 2
        print(
            f"\n  Control is non-empty, so the absence is real: no {GATE_WORKFLOW} run "
            f"exists for this commit. Its gates have never seen it."
        )
        return 1

    total_failed = 0
    total_starved = 0
    for run in gates:
        print()
        failed, starved = report_run(run)
        total_failed += failed
        total_starved += starved

    print()
    print(
        f"=== {len(gates)} {GATE_WORKFLOW} run(s): {total_failed} failed steps, "
        f"{total_starved} starved jobs ==="
    )
    if total_failed or total_starved:
        return 1
    print("No step failed and no job was starved. A skipped job is reported above by name;")
    print("read the split rather than a job count, because both have no runner.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
