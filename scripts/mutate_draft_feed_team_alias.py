"""Mutation harness for ``draft-feed-team-alias-draftteamid``.

**Injection, not deletion.** Each mutation puts back a specific defect the new
tests name and asks whether they go red. Removing an assertion is green by
construction and proves nothing about whether the assertion was ever doing the
work.

The headline is ``M01``: it restores ``FIELD_ALIASES["team_external_id"]`` to
the exact tuple that was on ``main`` before this unit. That is the state the
owner's first instrumented capture was run against, so if the new tests do not
go red on M01 they are not testing the defect that was found.

**Red is not enough, and this harness will not accept it.** ``gates.md``
records four separate occasions where a red arrived for a reason other than the
one claimed. So every mutation here declares *which test* must fail and *which
reason* must appear on an ``E``-prefixed assertion line — the ``E`` prefix
matters, because these tests name ``no_seat_anchor`` in their own docstrings and
pytest prints the docstring in the traceback. A substring search alone would
match the prose and pass for exactly the wrong reason.

``M06`` is the **over-refusal control**. A "fix" that refused every record would
satisfy any test phrased as "the wrong seat never appears" while being worse
than the defect, because a board that never fills is indistinguishable from a
draft that has not started. It forces that behaviour and the positive
assertions must go red.

``M07`` is the **do-not-touch control** for ``scorerId``. The backlog item is
explicit that the player alias is correct and must not be edited; this asserts
the new tests would notice if someone "cleaned it up" anyway.

Scoring rules, each of which a harness in this repository has previously got
wrong:

* An anchor not found **exactly once** is a HARNESS FAILURE, not a catch.
* A collection error, an import error or a crash is a HARNESS FAILURE.
* Only a genuine test *failure* naming the expected test and reason is CAUGHT.
* The baseline is asserted green before any mutation, every file is asserted
  byte-identical afterwards, and the baseline is re-run green at the end.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "backend"

# hoops_gm otherwise resolves to a stale user-site namespace package. Set here
# so the harness runs without the caller having remembered to.
ENV = {**os.environ, "PYTHONPATH": str(SRC / "src")}

TESTS = [
    "tests/test_draft_feed.py",
    "tests/test_drafts_api.py",
]

REC = "src/hoops_gm/draft/feed/recognise.py"

#: The tuple as it stands after this unit, written once so every mutation
#: anchors on the same text and a later edit to it fails loudly here rather
#: than silently skipping.
WIDENED = (
    '    "team_external_id": (\n'
    '        "draftTeamId",\n'
    '        "cellTeamId",\n'
    '        "teamId",\n'
    '        "fantasyTeamId",\n'
    '        "franchiseId",\n'
    '        "teamID",\n'
    "    ),"
)

SEAT = "test_the_team_key_a_live_draft_room_emits_resolves_to_a_seat"
ORDER = "test_a_record_naming_several_team_keys_is_read_by_alias_order_not_key_order"

#: ``E``-prefixed, because both tests print ``no_seat_anchor`` in their own
#: docstrings and pytest renders the docstring above the failure.
ANCHOR_REFUSAL = r"^E\s+.*no_seat_anchor"

# name, file, anchor, replacement, test that must fail, regex the failure must show
MUTATIONS: list[tuple[str, str, str, str, str, str]] = [
    (
        "M01 the original defect: the tuple exactly as it was on main",
        REC,
        WIDENED,
        '    "team_external_id": ("teamId", "fantasyTeamId", "franchiseId", "teamID"),',
        SEAT,
        ANCHOR_REFUSAL,
    ),
    (
        "M02 only draftTeamId is dropped",
        REC,
        '        "draftTeamId",\n        "cellTeamId",\n',
        '        "cellTeamId",\n',
        SEAT,
        ANCHOR_REFUSAL,
    ),
    (
        "M03 only cellTeamId is dropped",
        REC,
        '        "cellTeamId",\n        "teamId",\n',
        '        "teamId",\n',
        SEAT,
        ANCHOR_REFUSAL,
    ),
    (
        "M04 the generic name sorts first, so teamId wins over draftTeamId",
        REC,
        '        "draftTeamId",\n        "cellTeamId",\n        "teamId",\n',
        '        "teamId",\n        "draftTeamId",\n        "cellTeamId",\n',
        ORDER,
        r"^E\s+.*assert \['t3'\] == \['t1'\]",
    ),
    (
        "M05 precedence decided by the record's key order instead of by this tuple",
        REC,
        "def _first(record: dict[str, Any], field: str) -> Any:\n"
        "    for alias in FIELD_ALIASES[field]:",
        "def _first(record: dict[str, Any], field: str) -> Any:\n"
        "    for alias in [k for k in record if k in FIELD_ALIASES[field]]:",
        ORDER,
        r"^E\s+.*assert \['t6'\] == \['t1'\]",
    ),
    (
        "M06 CONTROL: every record refused, so the board never fills",
        REC,
        "        if team is None or team not in context.team_external_ids:",
        "        if True:",
        SEAT,
        ANCHOR_REFUSAL,
    ),
    (
        "M07 CONTROL: scorerId 'cleaned up' out of the player aliases",
        REC,
        '    "player_external_id": ("playerId", "scorerId", "fantasyPlayerId"),',
        '    "player_external_id": ("playerId", "fantasyPlayerId"),',
        SEAT,
        r"^E\s+.*assert \[None, None\] == \['06s74', '06s75'\]",
    ),
]


def run(args: list[str]) -> tuple[int, str]:
    """Run the suites, always to completion.

    **No ``-x``, deliberately.** An earlier version stopped at the first
    failure, and the over-refusal control then reported ``WRONG_TEST``: it
    reddened a *pre-existing* positive control that sits earlier in the file,
    so the run never reached the tests the control exists to exercise. A
    harness that stops before the test it is asking about cannot answer the
    question, and "something went red" is the answer this repository keeps
    finding was not enough.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *args,
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=SRC,
        env=ENV,
        capture_output=True,
        text=True,
        check=False,  # a non-zero rc is the signal, not an error
    )
    return proc.returncode, proc.stdout + proc.stderr


def classify(rc: int, out: str, *, expect_test: str, expect_reason: str) -> str:
    """Verdict for one mutation run.

    A collection error is a harness failure rather than a catch: pytest exits
    non-zero on a tree that does not import, and that red says nothing about
    the mutation.
    """
    if "INTERNALERROR" in out:
        return "HARNESS_FAILURE(internal error)"
    if re.search(r"\b(\d+) errors?\b", out) or "errors during collection" in out:
        return "HARNESS_FAILURE(collection/error)"
    if "SyntaxError" in out or "ImportError" in out:
        return "HARNESS_FAILURE(source did not import)"
    if rc == 5:
        return "HARNESS_FAILURE(no tests collected)"
    if rc == 4:
        return "HARNESS_FAILURE(usage error)"
    if rc == 2:
        return "HARNESS_FAILURE(interrupted)"
    if rc == 0:
        return "SURVIVED"
    match = re.search(r"(\d+) failed", out)
    if rc != 1 or not match:
        return f"HARNESS_FAILURE(rc={rc})"

    failed = re.findall(r"FAILED (\S+)", out)
    named = [name.split("::")[-1] for name in failed]
    matched = [name for name in named if name.startswith(expect_test)]
    if not matched:
        return f"WRONG_TEST(expected {expect_test}, got {named or ['unnamed']})"
    if not re.search(expect_reason, out, re.MULTILINE):
        return f"WRONG_REASON(no assertion line matching {expect_reason!r})"
    return f"CAUGHT({match.group(1)} failed, incl. {matched[0]})"


def main() -> int:
    # Optional argv filter, so one mutation can be re-run without a full sweep.
    wanted = sys.argv[1:]
    selected = [m for m in MUTATIONS if not wanted or any(w in m[0] for w in wanted)]
    if not selected:
        print(f"no mutation matches {wanted}")
        return 1

    print("=== baseline ===")
    rc, out = run(TESTS)
    base = re.search(r"(\d+) passed", out)
    if rc != 0 or not base:
        print(f"BASELINE NOT GREEN rc={rc}; refusing to mutate")
        print(out[-3000:])
        return 1
    print(f"baseline: {base.group(1)} passed, rc=0\n")

    originals = {
        path: (SRC / path).read_text(encoding="utf-8") for path in {m[1] for m in MUTATIONS}
    }

    caught = survived = harness = 0
    for name, rel, old, new, expect_test, expect_reason in selected:
        path = SRC / rel
        text = originals[rel]
        found = text.count(old)
        if found != 1:
            print(f"[{name}] HARNESS_FAILURE(anchor found {found} times, expected 1)")
            harness += 1
            continue
        mutated = text.replace(old, new, 1)
        if mutated == text:
            print(f"[{name}] HARNESS_FAILURE(mutation changed nothing)")
            harness += 1
            continue
        path.write_text(mutated, encoding="utf-8")
        try:
            assert path.read_text(encoding="utf-8") == mutated, "mutation not on disk"
            rc, out = run(TESTS)
            verdict = classify(rc, out, expect_test=expect_test, expect_reason=expect_reason)
        finally:
            path.write_text(text, encoding="utf-8")
        print(f"[{name}] {verdict}")
        if verdict.startswith("CAUGHT"):
            caught += 1
        elif verdict == "SURVIVED":
            survived += 1
        else:
            harness += 1

    for rel, text in originals.items():
        assert (SRC / rel).read_text(encoding="utf-8") == text, f"{rel} not restored"

    # The other half of "assert green before mutating": a sweep that leaves the
    # tree red is not a sweep whose verdicts can be trusted, and a restore that
    # was byte-correct but landed beside some other write would still show up
    # here.
    print("\n=== baseline after restore ===")
    rc, out = run(TESTS)
    after = re.search(r"(\d+) passed", out)
    if rc != 0 or not after:
        print(f"NOT GREEN AFTER RESTORE rc={rc}")
        print(out[-3000:])
        return 1
    print(f"restored: {after.group(1)} passed, rc=0")

    print(
        f"\n=== {len(selected)} mutations: {caught} caught, "
        f"{survived} survived, {harness} harness failures ==="
    )
    return 0 if survived == 0 and harness == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
