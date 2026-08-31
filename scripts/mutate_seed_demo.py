"""Mutation harness for the composed demo seed.

Same scoring rules as ``mutate_aav.py``, and for the same reasons: an anchor not
found **exactly once** is a harness failure rather than a catch; a collection
error, ``rc 5`` (nothing collected) and ``rc 4`` (usage error) are harness
failures rather than catches; only ``rc 1`` with a parsed ``N failed`` counts as
CAUGHT; the baseline is asserted green before anything is mutated and every
touched file asserted byte-identical afterwards.

**Do not run this concurrently with a test suite.** It edits source in place, so
an overlapping run reads a mutated tree.

What each mutation is aimed at, because a red for an adjacent reason is not
attribution:

* **M01/M02** reproduce the defect this unit exists to fix — the draft state and
  the schedule/projection state failing to share one database, either by being
  seeded in the order that refuses or by not being seeded at all. If the
  acceptance test survives either of these it is not testing the composition.
* **M03** checks the dashboard-league test is pinned by the constant it names
  rather than passing because 1 is what an autoincrement happens to produce.
* **M04/M05** are the two arms of ``looks_like_a_previous_demo_seed``. A hint
  that fires on every database is worse than no hint, so ``any`` surviving would
  matter as much as ``all`` surviving.
* **M06** disables the guard in ``seed_schedule_grid`` that both the ordering
  test and the rollback test rest on, so a green there would mean those two
  tests are held up by something other than the refusal they describe.
* **M07** is the rollback test's own defect, reconstructed: a ``commit`` between
  the two seeders is precisely what composing them at the shell does, and it is
  the only mutation that distinguishes "one atomic session" from "the refusal
  happened to fire before anything was written".
* **M08-M11** cover the real-store gap found on 2026-08-23. M08 and M09 are the
  two signals separately, because either can occur without the other and a
  single test planting both would survive deleting one. M10 removes the call
  rather than the check, which is the failure a reader would not see by reading
  the function. **M11 is the one that matters most and is easiest to get
  wrong**: the absent-table skip exists so a half-built schema gets a clean
  refusal instead of an ``OperationalError``, and widening it to skip a table
  that *is* present turns the whole guard into a no-op that still looks like a
  guard. It must be caught by a test that plants real evidence, not by one that
  merely reaches the function.
* **M12** reproduces the category-screen defect: the composed seed calls the
  standalone draft path and discards the exact projection-cohort IDs it just
  selected. Both API responses still answer 200, so only the end-to-end join
  assertion catches it.
* **M13** disables the canonical-cohort lower bound. The six-player CLI then
  returns a success-shaped partial auction again, and the direct boundary test
  proves the refusal had to happen before the first draft write.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "backend"

# hoops_gm otherwise resolves to a stale user-site namespace package.
#
# PYTHONIOENCODING is set for a second, separate reason. `docs/handoff.md`
# records that a `subprocess` call reading a repository file on this machine
# needs `encoding="utf-8"`, because Windows defaults to cp1252 and the tree is
# UTF-8. **The opposite direction is the trap here**: a child process's console
# output is encoded by the *child*, in cp1252, so declaring `encoding="utf-8"`
# on the read side raises `UnicodeDecodeError` on the first em dash in a test
# docstring. The fix is to make the producer agree rather than to guess harder
# on the consumer — plus `errors="replace"` below, because this text is only
# ever fed to a regex and a mangled character must never be able to turn a real
# verdict into a harness crash.
ENV = {
    **os.environ,
    "PYTHONPATH": str(SRC / "src"),
    "PYTHONIOENCODING": "utf-8",
}

TESTS = ["tests/test_seed_demo.py"]

DEMO = "src/hoops_gm/dev/seed_demo.py"
DRAFT = "src/hoops_gm/dev/seed_draft.py"
GRID = "src/hoops_gm/dev/seed_schedule_grid.py"

MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "M01 drafts seeded before projections (the ordering that refuses)",
        DEMO,
        "    projections = seed_projections(session, fixtures_dir=fixtures_dir,"
        " cohort_size=cohort_size)",
        "    drafts = seed_drafts(session)\n    projections = seed_projections("
        "session, fixtures_dir=fixtures_dir, cohort_size=cohort_size)",
    ),
    (
        "M02 draft state never seeded into this database (the original defect)",
        DEMO,
        "    drafts = seed_drafts(session, auction_players=auction_players)",
        "    drafts = DraftSeedResult(0, 0, 0, 0, 0, 0, 0, 0)",
    ),
    (
        "M03 dashboard league constant moved off 1",
        DEMO,
        "FRONTEND_LEAGUE_ID = 1",
        "FRONTEND_LEAGUE_ID = 2",
    ),
    (
        "M04 repeat-run hint fires when *any* league is ours, not all",
        DEMO,
        "    return all(\n        fantrax_league_id == FANTRAX_LEAGUE_ID"
        " or name.startswith(DEMO_PREFIX)",
        "    return any(\n        fantrax_league_id == FANTRAX_LEAGUE_ID"
        " or name.startswith(DEMO_PREFIX)",
    ),
    (
        "M05 empty-database early return removed (all([]) is True)",
        DEMO,
        "    if not leagues:\n        return False",
        "    if False:\n        return False",
    ),
    (
        "M06 foreign-league refusal disabled in the schedule seed",
        GRID,
        "    if foreign_league is not None:",
        "    if False:",
    ),
    (
        "M07 the two seeders commit separately (composing at the shell)",
        DEMO,
        "    projections = seed_projections(session, fixtures_dir=fixtures_dir,"
        " cohort_size=cohort_size)",
        "    projections = seed_projections(session, fixtures_dir=fixtures_dir,"
        " cohort_size=cohort_size)\n    session.commit()",
    ),
    (
        "M08 participation-ledger refusal never fires (the real-store gap)",
        GRID,
        "        if participation is not None:",
        "        if False:",
    ),
    (
        "M09 foreign-season refusal never fires",
        GRID,
        "        if foreign_season is not None:",
        "        if False:",
    ),
    (
        "M10 real-ingest check not called at all",
        GRID,
        "    _require_no_real_ingest(session)",
        "    pass  # mutated",
    ),
    (
        "M11 absent-table skip widened to skip a present one",
        GRID,
        "    tables = set(inspect(session.get_bind()).get_table_names())",
        "    tables = set()",
    ),
    (
        "M12 composed draft drops the projection-cohort player IDs",
        DEMO,
        "    drafts = seed_drafts(session, auction_players=auction_players)",
        "    drafts = seed_drafts(session)",
    ),
    (
        "M13 short canonical auction cohort guard disabled",
        DRAFT,
        "    _require_complete_auction_players(selection_players)\n    league = _demo_league(",
        "    league = _demo_league(",
    ),
]


def run(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *args, "--no-header", "-p", "no:cacheprovider"],
        cwd=SRC,
        env=ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,  # a non-zero rc is the signal, not an error
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def classify(rc: int, out: str) -> str:
    if re.search(r"error|ERROR|INTERNALERROR", out) and "errors" in out:
        return "HARNESS_FAILURE(collection/error)"
    if rc == 5:
        return "HARNESS_FAILURE(no tests collected)"
    if rc == 4:
        return "HARNESS_FAILURE(usage error)"
    failed = re.search(r"(\d+) failed", out)
    if rc == 1 and failed:
        return f"CAUGHT({failed.group(1)} failed)"
    if rc == 0:
        return "SURVIVED"
    return f"HARNESS_FAILURE(rc={rc})"


def main() -> int:
    print("=== baseline ===")
    rc, out = run(TESTS)
    base = re.search(r"(\d+) passed", out)
    if rc != 0 or not base:
        print(f"BASELINE NOT GREEN rc={rc}; refusing to mutate")
        print(out[-2000:])
        return 1
    print(f"baseline: {base.group(1)} passed, rc=0")

    originals = {p: (SRC / p).read_text(encoding="utf-8") for p in {m[1] for m in MUTATIONS}}

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
        path.write_text(mutated, encoding="utf-8")
        # A mutation that did not apply looks exactly like a guard that works.
        if path.read_text(encoding="utf-8") == text:
            path.write_text(text, encoding="utf-8")
            print(f"[{name}] HARNESS_FAILURE(mutation did not change the file)")
            harness += 1
            continue
        try:
            rc, out = run(TESTS)
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
