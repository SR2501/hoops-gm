"""Mutation harness for the aav-source unit.

Scoring rules this harness obeys, each of which a harness elsewhere today got wrong:

* An anchor that is not found **exactly once** is a HARNESS FAILURE, not a catch.
  A CRLF checkout produced nine anchor-count-0 "catches" for a reviewer today.
* A collection error, an import error or a crash is a HARNESS FAILURE, not a catch.
  Scoring every crash as a pass is how a harness reports success about nothing.
* Only a genuine test *failure* (rc 1 with a parsed "N failed" line) counts as CAUGHT.
* The baseline is asserted green before any mutation is applied, and the tree is
  asserted byte-identical afterwards.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "backend"

# hoops_gm otherwise resolves to a stale user-site namespace package, and an
# editable .pth pointing at a deleted worktree. Set it here so the harness is
# runnable without the caller having remembered to.
ENV = {**os.environ, "PYTHONPATH": str(SRC / "src")}

TESTS = [
    "tests/test_auction_value_import.py",
    "tests/test_auction_value_import_cli.py",
]

IND = "src/hoops_gm/market/independence.py"
IMP = "src/hoops_gm/ingest/auction_values/importer.py"
MOD = "src/hoops_gm/ingest/auction_values/models.py"
PAR = "src/hoops_gm/ingest/auction_values/parser.py"

MUTATIONS: list[tuple[str, str, str, str]] = [
    # --- the guard: lineage ---
    (
        "M01 lineage overlap never detected",
        IND,
        "if item.our_projection_source is not None and item.our_projection_source in ours",
        "if False",
    ),
    (
        "M02 circular finding made admissible",
        IND,
        "                code=CIRCULAR_LINEAGE,\n                admissible=False,",
        "                code=CIRCULAR_LINEAGE,\n                admissible=True,",
    ),
    (
        "M03 unestablished lineage made admissible (the fail-open we fixed)",
        IND,
        "                code=LINEAGE_UNESTABLISHED,\n                admissible=False,",
        "                code=LINEAGE_UNESTABLISHED,\n                admissible=True,",
    ),
    (
        "M04 unestablished-lineage refusal removed entirely",
        IND,
        "    if not inputs:",
        "    if False:",
    ),
    (
        "M05 derivation-unestablished caveat dropped",
        IND,
        "    elif source.derivation_method is AuctionValueDerivation.UNESTABLISHED:",
        "    elif False:",
    ),
    (
        "M06 inferred-basis finding dropped at consumption",
        IND,
        "    if inferred:",
        "    if False:",
    ),
    (
        "M07 inferred-basis test reverted to identity comparison",
        IND,
        "if getattr(auction_import, evidence_column) == BasisEvidence.INFERRED",
        "if getattr(auction_import, evidence_column) is BasisEvidence.INFERRED",
    ),
    # --- the importer: counts ---
    (
        "M08 rejected_count zeroed",
        IMP,
        "    auction_import.rejected_count = len(parsed.fully_rejected_row_numbers)",
        "    auction_import.rejected_count = 0",
    ),
    (
        "M09 rejected_count at the wrong grain (the C defect)",
        IMP,
        "    auction_import.rejected_count = len(parsed.fully_rejected_row_numbers)",
        "    auction_import.rejected_count = len(parsed.rejected_row_numbers)",
    ),
    (
        "M10 partition assertion removed",
        IMP,
        "    if auction_import.rejected_count + len(parsed.rows_yielding_values) != parsed.total_rows:",
        "    if False:",
    ),
    (
        "M11 row_count hardcoded to 10 (the defect that survived once)",
        IMP,
        "    auction_import.row_count = parsed.total_rows",
        "    auction_import.row_count = 10",
    ),
    (
        "M12 duplicate-player refusal removed",
        IMP,
        "    _refuse_duplicate_player_rows(parsed)",
        "    pass  # mutated",
    ),
    (
        "M13 checksum CRLF normalisation removed",
        IMP,
        'return hashlib.sha256(payload.replace(b"\\r\\n", b"\\n")).hexdigest()',
        "return hashlib.sha256(payload).hexdigest()",
    ),
]


def run(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *args, "--no-header", "-p", "no:cacheprovider"],
        cwd=SRC,
        env=ENV,
        capture_output=True,
        text=True,
        check=False,  # a non-zero rc is the signal, not an error
    )
    return proc.returncode, proc.stdout + proc.stderr


def classify(rc: int, out: str) -> str:
    if re.search(r"error|ERROR|INTERNALERROR", out) and "errors" in out:
        return "HARNESS_FAILURE(collection/error)"
    if rc == 5:
        return "HARNESS_FAILURE(no tests collected)"
    if rc == 4:
        return "HARNESS_FAILURE(usage error)"
    m = re.search(r"(\d+) failed", out)
    if rc == 1 and m:
        return f"CAUGHT({m.group(1)} failed)"
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
        n = text.count(old)
        if n != 1:
            print(f"[{name}] HARNESS_FAILURE(anchor found {n} times, expected 1)")
            harness += 1
            continue
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
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

    # prove we restored everything
    for rel, text in originals.items():
        assert (SRC / rel).read_text(encoding="utf-8") == text, f"{rel} not restored"

    print(
        f"\n=== {len(MUTATIONS)} mutations: {caught} caught, "
        f"{survived} survived, {harness} harness failures ==="
    )
    return 0 if survived == 0 and harness == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
