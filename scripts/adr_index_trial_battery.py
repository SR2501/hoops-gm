"""Common mutation battery for the 2026-09-05 model trial.

Scores an arm's ``adr-index-consistency-test`` implementation against planted
defects in ``docs/decisions/`` that no arm saw. The battery is defined in
``docs/governance/model-trial-2026-09-05-preregistration.md`` and was fixed
before any arm ran; this file only implements it.

It lives in the repository because ``docs/governance/gates.md`` requires that a
tool whose output is cited as evidence be readable by whoever reads the number.
A harness kept outside the tree once carried a unit for nine review rounds with
nobody able to check its figure.

Scoring rules, each inherited from a failure this repository already had:

* An anchor not found **exactly once** is a HARNESS FAILURE, not a catch.
* A crash, collection error or usage error is a HARNESS FAILURE, not a catch.
* ``no tests collected`` is a HARNESS FAILURE. A test file that collects nothing
  otherwise looks exactly like a suite that never fails.
* Only a genuine test *failure* counts as CAUGHT.
* The clean-tree control must PASS; a test red on an unmutated tree is not a
  test, and no count of caught mutations redeems it.
* The tree is asserted byte-identical after every entry, so one entry cannot
  contaminate the next.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DECISIONS = Path("docs/decisions")
README = DECISIONS / "README.md"
PLAIN = DECISIONS / "PLAIN-ENGLISH.md"

ADR_013_ROW = "| [013](ADR-013-forward-schedule-completeness.md) |"
ADR_014_LINK = "[014](ADR-014-read-endpoints-detect-not-lock.md)"
# ADR-018 is the one late row appearing exactly once at the base commit: 002, 007,
# 019 and 020 all recur in the README's second (amendments) table, so anchoring on
# any of them would trip the exactly-once rule rather than mutate anything.
ADR_018_ROW = "| [018](ADR-018-calibration-displayed-beside-the-number.md) |"
INVENTED_ROW = "| [042](ADR-042-invented.md) | Invented for the battery | *Proposed* | none |"


@dataclass(frozen=True)
class Entry:
    """One battery entry: what to break, and the verdict a correct test returns."""

    ident: str
    tier: str
    summary: str = ""
    expect: str = "FAIL"
    # exactly one of the following applies
    sub: tuple[Path, str, str] | None = None
    drop_line_prefix: tuple[Path, str] | None = None
    rename: tuple[Path, Path] | None = None
    copy: tuple[Path, Path] | None = None
    append: tuple[Path, str] | None = None


BATTERY: list[Entry] = [
    Entry(
        "B8",
        "CORE",
        summary="clean tree, nothing mutated - the ADR-016 reservation trap",
        expect="PASS",
    ),
    Entry(
        "B1",
        "CORE",
        summary="README row deleted for an ADR that exists (the real 2026-08-21 defect)",
        drop_line_prefix=(README, ADR_013_ROW),
    ),
    Entry(
        "B2",
        "CORE",
        summary="README row present for an ADR file that does not exist",
        sub=(README, ADR_018_ROW, f"{INVENTED_ROW}\n{ADR_018_ROW}"),
    ),
    Entry(
        "B4",
        "CORE",
        summary="README link repointed at a filename that does not exist",
        sub=(README, ADR_014_LINK, "[014](ADR-014-does-not-exist.md)"),
    ),
    Entry(
        "B5",
        "CORE",
        summary="ADR file renamed so its number matches no row",
        rename=(
            DECISIONS / "ADR-011-strength-of-schedule-sequencing.md",
            DECISIONS / "ADR-099-strength-of-schedule-sequencing.md",
        ),
    ),
    Entry(
        "B6",
        "CORE",
        summary="duplicate ADR number across two files",
        copy=(
            DECISIONS / "ADR-012-per-week-game-distribution.md",
            DECISIONS / "ADR-012-duplicate-copy.md",
        ),
    ),
    Entry(
        "B3",
        "EXTENDED",
        summary="README Status cell contradicts the ADR's own Status line",
        sub=(
            README,
            "they do not lock to prevent one | *Proposed* |",
            "they do not lock to prevent one | **Accepted** |",
        ),
    ),
    Entry(
        "B7",
        "EXTENDED",
        summary="PLAIN-ENGLISH names an ADR that does not exist",
        append=(PLAIN, "\nSee [ADR-042-invented.md](ADR-042-invented.md).\n"),
    ),
]


class HarnessFailure(RuntimeError):
    """Raised when the battery cannot establish anything, rather than guessing."""


def _apply(root: Path, e: Entry) -> list[tuple[Path, bytes | None]]:
    """Apply one entry. Returns undo records of (path, original bytes or None)."""
    undo: list[tuple[Path, bytes | None]] = []

    if e.sub is not None:
        rel, old, new = e.sub
        p = root / rel
        text = p.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise HarnessFailure(f"{e.ident}: anchor found {text.count(old)}x, need exactly 1")
        undo.append((p, p.read_bytes()))
        p.write_text(text.replace(old, new), encoding="utf-8", newline="")

    if e.drop_line_prefix is not None:
        rel, prefix = e.drop_line_prefix
        p = root / rel
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        hits = [i for i, ln in enumerate(lines) if ln.startswith(prefix)]
        if len(hits) != 1:
            raise HarnessFailure(
                f"{e.ident}: line prefix matched {len(hits)} lines, need exactly 1"
            )
        undo.append((p, p.read_bytes()))
        del lines[hits[0]]
        p.write_text("".join(lines), encoding="utf-8", newline="")

    if e.rename is not None:
        src, dst = (root / e.rename[0], root / e.rename[1])
        if not src.exists() or dst.exists():
            raise HarnessFailure(f"{e.ident}: rename precondition failed")
        undo.append((dst, None))
        undo.append((src, src.read_bytes()))
        src.rename(dst)

    if e.copy is not None:
        src, dst = (root / e.copy[0], root / e.copy[1])
        if not src.exists() or dst.exists():
            raise HarnessFailure(f"{e.ident}: copy precondition failed")
        undo.append((dst, None))
        shutil.copyfile(src, dst)

    if e.append is not None:
        rel, extra = e.append
        p = root / rel
        undo.append((p, p.read_bytes()))
        p.write_bytes(p.read_bytes() + extra.encode("utf-8"))

    return undo


def _undo(records: list[tuple[Path, bytes | None]]) -> None:
    for path, original in reversed(records):
        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.write_bytes(original)


def _run_test(root: Path, test_rel: str) -> tuple[str, str]:
    """Run the arm's test. Returns (verdict, detail) where verdict is PASS/FAIL/HARNESS."""
    env = {**os.environ, "PYTHONPATH": str(root / "backend" / "src")}
    try:
        proc = subprocess.run(
            # No `-q` here on purpose. backend/pyproject.toml's addopts already
            # carries one; adding a second makes pytest `-qq`, which suppresses
            # the "N failed" summary line. Validation caught this: an
            # always-failing probe was classified HARNESS rather than FAIL,
            # which in a real run would have scored a genuine catch as a broken
            # harness. The classifier below is now exit-code-primary so it
            # survives an addopts change too.
            [sys.executable, "-m", "pytest", test_rel, "-p", "no:cacheprovider"],
            cwd=root / "backend",
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return "HARNESS", "timeout"

    tail = (proc.stdout + proc.stderr).strip().splitlines()
    detail = tail[-1][:200] if tail else f"rc={proc.returncode}"
    blob = proc.stdout + proc.stderr

    if proc.returncode == 5 or "no tests ran" in blob:
        return "HARNESS", f"no tests collected: {detail}"
    if re.search(r"\d+ error", blob) or proc.returncode in (2, 3, 4):
        return "HARNESS", f"error/interrupt rc={proc.returncode}: {detail}"
    if proc.returncode == 0:
        return "PASS", detail
    if proc.returncode == 1:
        return "FAIL", detail
    return "HARNESS", f"unclassified rc={proc.returncode}: {detail}"


def _tree_digest(root: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    for p in sorted((root / DECISIONS).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--root", required=True, help="scratch worktree holding the arm's files")
    ap.add_argument("--test", required=True, help="test path relative to backend/")
    ap.add_argument("--json-out")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    baseline = _tree_digest(root)
    results: list[dict[str, object]] = []

    for e in BATTERY:
        undo: list[tuple[Path, bytes | None]] = []
        try:
            undo = _apply(root, e)
            verdict, detail = _run_test(root, args.test)
        except HarnessFailure as exc:
            verdict, detail = "HARNESS", str(exc)
        finally:
            _undo(undo)

        after = _tree_digest(root)
        if after != baseline:
            raise SystemExit(f"{e.ident}: tree not restored - refusing to continue")

        scored = "OK" if verdict == e.expect else ("HARNESS" if verdict == "HARNESS" else "MISS")
        results.append(
            {
                "id": e.ident,
                "tier": e.tier,
                "summary": e.summary,
                "expected": e.expect,
                "observed": verdict,
                "scored": scored,
                "detail": detail,
            }
        )
        print(
            f"{e.ident:<4} {e.tier:<8} expect={e.expect:<4} "
            f"got={verdict:<7} {scored:<7} {e.summary}"
        )

    core = [r for r in results if r["tier"] == "CORE"]
    ext = [r for r in results if r["tier"] == "EXTENDED"]
    b8 = next(r for r in results if r["id"] == "B8")
    summary = {
        "arm": args.arm,
        "core_ok": sum(1 for r in core if r["scored"] == "OK"),
        "core_total": len(core),
        "extended_ok": sum(1 for r in ext if r["scored"] == "OK"),
        "extended_total": len(ext),
        "harness_failures": sum(1 for r in results if r["scored"] == "HARNESS"),
        "b8_clean_tree": b8["observed"],
        "vetoed": b8["observed"] != "PASS",
        "results": results,
    }

    print(
        f"\n{args.arm}: CORE {summary['core_ok']}/{summary['core_total']}  "
        f"EXTENDED {summary['extended_ok']}/{summary['extended_total']}  "
        f"harness-failures {summary['harness_failures']}  "
        f"B8 {summary['b8_clean_tree']}"
        + ("  *** VETOED: red on a clean tree ***" if summary["vetoed"] else "")
    )

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
