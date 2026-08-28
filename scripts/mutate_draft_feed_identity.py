"""Mutation harness for ``draft-feed-unreadable-id-surfacing``.

**Injection, not deletion.** Every mutation below puts back a specific defect
the unit's tests name, and the harness reports whether the suite goes red. That
is a different question from whether an assert can be removed: removing an
assert is green by construction and proves nothing about whether the assert was
ever the thing doing the work.

The headline is ``M01``. It reverts the change to exactly the state the backlog
records — the unreadable record is still *counted* on the ``POST`` ingest
response and no longer reaches storage, so ``GET`` reports nothing. If the new
tests do not go red on M01, they are not testing the defect.

Scoring rules, each of which a harness in this repository has previously got
wrong:

* An anchor not found **exactly once** is a HARNESS FAILURE, not a catch. A
  CRLF checkout once produced nine anchor-count-0 "catches".
* A collection error, an import error or a crash is a HARNESS FAILURE.
* Only a genuine test *failure* (rc 1 with a parsed "N failed") counts as
  CAUGHT.
* The baseline is asserted green before any mutation, and every file is
  asserted byte-identical afterwards.

``M07`` is the **over-refusal control** and is the one that is not about
coverage. A "fix" that refused every record would pass the defect tests while
being worse than the defect, because a board that never fills looks exactly
like a draft that has not started. M07 forces that behaviour and the ordinary
captures must go red.
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
    "tests/test_migrations.py",
]

REC = "src/hoops_gm/draft/feed/recognise.py"
SVC = "src/hoops_gm/draft/feed/service.py"
OBS = "src/hoops_gm/draft/feed/observations.py"
MOD = "src/hoops_gm/db/models/draft_feed.py"
MIG = "alembic/versions/0021_draft_feed_unreadable_identity.py"

MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "M01 the original defect: counted at POST, never stored, absent from GET",
        REC,
        "            for position, record in unreadable:",
        "            for position, record in []:",
    ),
    (
        "M02 the refusal is dropped before it is even counted",
        REC,
        "            unreadable.append((position, record))",
        "            pass  # mutated",
    ),
    (
        "M03 the row is stored but says nothing, so it is pending and appliable",
        SVC,
        "            skipped_reason=instant.skipped_reason,",
        "            skipped_reason=None,",
    ),
    (
        "M04 a refused record keeps a label, so it joins identity matching",
        REC,
        "    if skipped_reason is not None:\n        return ObservedInstant(",
        "    if False:\n        return ObservedInstant(",
    ),
    (
        "M05 nameless rows are counted as readings again (freshness false all-clear)",
        SVC,
        "    instants = [_to_instant(row) for row in rows if names_a_player(row)]",
        "    instants = [_to_instant(row) for row in rows]",
    ),
    (
        "M06 the official path goes back to dropping an unidentifiable record",
        REC,
        "            unnamed += 1\n",
        "            unnamed += 1\n            continue\n",
    ),
    (
        "M07 CONTROL: every record refused, so the board never fills",
        REC,
        "        if isinstance(identity, _Unreadable):",
        "        if True:",
    ),
    (
        "M08 a refusal is counted as a reading the recogniser understood",
        OBS,
        "        return sum(1 for instant in self.instants if instant.skipped_reason is None)",
        "        return len(self.instants)",
    ),
    (
        "M09 the refusal reuses the admitted record's locator slot",
        REC,
        '                            locator=f"{list_locator}[{position}]",\n'
        "                        ),\n"
        '                        skipped_reason="player_external_id_unreadable",',
        '                            locator=f"{list_locator}[0]",\n'
        "                        ),\n"
        '                        skipped_reason="player_external_id_unreadable",',
    ),
    (
        "M10 the model CHECK never widened, so the nameless row is refused at flush",
        MOD,
        '            "player_label IS NOT NULL OR player_external_id IS NOT NULL"\n'
        '            " OR skipped_reason IS NOT NULL",',
        '            "player_label IS NOT NULL OR player_external_id IS NOT NULL",',
    ),
    (
        "M11 the migration never widened, so a migrated database refuses the row",
        MIG,
        '_WIDE = f"{_NARROW} OR skipped_reason IS NOT NULL"',
        "_WIDE = _NARROW",
    ),
    (
        "M12 the downgrade deletes rows that name a player",
        MIG,
        '            " WHERE player_label IS NULL AND player_external_id IS NULL"',
        '            " WHERE 1 = 1"',
    ),
    (
        "M13 the official path stops telling the two refusals apart",
        REC,
        "                if pick.player_id is not None or pick.player_name is not None",
        "                if False",
    ),
]


def run(args: list[str], *, stop_early: bool) -> tuple[int, str]:
    """Run the suites. ``stop_early`` is for mutation runs only.

    One failure is all a mutation needs to be CAUGHT, and this unit's suite is
    seventeen minutes end to end — without ``-x`` the harness would take longer
    to run than the change took to write, which is how a harness stops being
    run. The **baseline** deliberately does not use it: a baseline that stopped
    early would report green having skipped most of what it was proving.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *args,
            *(["-x"] if stop_early else []),
            "--no-header",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
        ],
        cwd=SRC,
        env=ENV,
        capture_output=True,
        text=True,
        check=False,  # a non-zero rc is the signal, not an error
    )
    return proc.returncode, proc.stdout + proc.stderr


def classify(rc: int, out: str) -> str:
    """Verdict for one mutation run.

    **A collection error is a harness failure, not a catch**, and this had to be
    learned the hard way on this very unit: a first sweep reported 13/13 caught
    while the author was concurrently editing the test file, and a
    ``SyntaxError`` there produces a red run that is not evidence about the
    mutation at all. ``gates.md`` already says a verdict on a tree that moved
    underneath it is not a verdict; this is the executable half of that.
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
    match = re.search(r"(\d+) failed", out)
    if rc == 1 and match:
        # Name the test, not just the count. "1 failed" says something went red;
        # it does not say the *right* thing went red, and on a suite this size
        # those are very different claims.
        failed = re.findall(r"FAILED (\S+)", out)
        named = failed[0].split("::")[-1] if failed else "unnamed"
        return f"CAUGHT({match.group(1)} failed: {named})"
    if rc == 0:
        return "SURVIVED"
    return f"HARNESS_FAILURE(rc={rc})"


def main() -> int:
    print("=== baseline ===")
    rc, out = run(TESTS, stop_early=False)
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
    for name, rel, old, new in MUTATIONS:
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
            rc, out = run(TESTS, stop_early=True)
            verdict = classify(rc, out)
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

    print(
        f"\n=== {len(MUTATIONS)} mutations: {caught} caught, "
        f"{survived} survived, {harness} harness failures ==="
    )
    return 0 if survived == 0 and harness == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
