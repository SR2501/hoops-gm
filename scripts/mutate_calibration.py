"""Mutation harness for the calibration machinery.

Same scoring rules as ``mutate_aav.py`` and ``mutate_seed_demo.py``, and for the
same reasons: an anchor not found **exactly once** is a harness failure rather
than a catch; a collection error, ``rc 5`` (nothing collected) and ``rc 4``
(usage error) are harness failures rather than catches; only ``rc 1`` with a
parsed ``N failed`` counts as CAUGHT; the baseline is asserted green before
anything is mutated and every touched file asserted byte-identical afterwards.

**Do not run this concurrently with a test suite.** It edits source in place.

Why this file exists at all: a calibration checker is exactly the kind of code
whose failure is silent. Every function it contains returns a plausible float for
any input, and a suite that only ever feeds it well-calibrated data passes
whether or not a single detector works. So each mutation below breaks one
detector, and the test that must go red is named beside it.

* **M01** disables the provenance guard. If a restricted report can still claim
  v2 pre-registration, the only structural thing standing between a
  ``Proposed`` amendment and a figure presented as pre-registered is a habit.
* **M02** drops the ``z^2/4n^2`` term from the Wilson interval — a transcription
  error that leaves the interval *nearly* right, which is why the test checks
  against the defining inequality rather than against a second copy of the
  closed form.
* **M03** makes expected calibration error an unweighted mean over bins. This is
  the same defect as scoring a 90% free-throw shooter on one attempt, and it
  flatters a model that is badly wrong in a small bin.
* **M04** flips the calibration-in-the-large sign. Nothing crashes; a model that
  over-predicts play is simply reported as under-predicting it, which inverts
  every start/sit reading of the number.
* **M05** flips the reversal comparison, so a model whose ordering is wrong is
  reported clean and a correct one is flagged.
* **M06** widens subgroup restriction from ``all`` to ``any``. A restriction that
  widens under a second key is not a restriction, and it would silently turn a
  status-and-era cell into a union.
* **M07** removes the rounding before distinct-probability grouping. Two
  arithmetically equal rates differing by one ulp then form two half-sized bins,
  which can fail the population floor for a numerical reason — a wrong veto.
* **M08** stops counting log-loss clips, so a log loss that is finite only
  because of a constant reports as if it were finite on its own merits.
* **M09**, **M10** disable the two per-bin conditions (population floor, emitted
  probability inside its own Wilson interval). Both are ``@property`` one-liners
  returning an empty tuple on success, so a broken one looks exactly like a
  clean model.
* **M11** returns ``exact_plays`` to banker's rounding, which sends 0.5 to 0.
  A generator whose play counts are off by one produces cohorts whose "known"
  calibration is not the known one, so every exact assertion downstream becomes
  approximately true for the wrong reason.
* **M12** infers band order instead of taking the declared one. Condition 7 is
  about a *prior* ordering; inferring it from the data is how a reversal becomes
  undetectable by construction.
* **M13** clips instead of refusing when an injected error leaves ``[0, 1]``.
  The cohort would still build, and the CITL identity it exists to demonstrate
  would quietly stop holding.
* **M14** leaves the final equal-width bin half-open, so a prediction of exactly
  1.0 falls outside every bin boundary the report prints.

**M15-M18 came from an independent reviewer, not from me.** He wrote nine
mutations of his own against `5032bf1` and four survived a suite that had just
caught fourteen. That is the useful number in this file: my own mutations tell
you what I thought to check, and his tell you what I did not.

* **M15** makes `build_calibration_report` ignore a cohort's inherited
  restriction, restoring the parameter-keyed guard the reviewer defeated in one
  line - pre-filter with `restrict()`, pass the result in as a whole cohort, and
  an 83-row subgroup claims `PREREGISTERED_V2` with `restriction: None`.
* **M16** makes a *missing* label key count as a match, which turns a
  restriction into a near-no-op while every subgroup assertion still passes,
  because the fixtures all happened to be fully labelled.
* **M17** swaps the 95% Wilson constant for the 90% one. Every interval was
  derived from that constant, so the suite agreed with itself at any value.
* **M18** swaps the bootstrap's 2.5% and 97.5% quantiles. v2 §8 condition 2
  reads the **upper** endpoint, so this converts a straddling interval into a
  pass - miscalibration in the direction that flatters the candidate.

**M19-M23 came from the same reviewer's second pass**, against the fixes for the
first. Two of the four fixes were incomplete in ways the fix's own tests could
not see, which is the argument for re-reviewing a fix rather than only the thing
it fixed.

* **M19** un-nests `restrict()` so an inner restriction is dropped, and a
  doubly-narrowed cohort reports only its outer pair - a payload that
  **under-reports** what was excluded.
* **M20** trusts the restriction marker instead of verifying it against the rows.
  A `RestrictedCohort` is a mutable list, so `extend` moves the data while the
  marker stands still, and the payload then **over-claims**: an `out`-dominated
  rate recorded as `doubtful`.
* **M21** returns a bare `list` from a slice again. `rc[:]` is a defensive-copy
  idiom rather than a laundering act, and it silently disarmed the guard.
* **M22** is the reviewer's P11 and **survived his own pass**: dropping the sort
  from `recorded_restriction` left every test green, because the one test that
  looked like it pinned the order applied its keys in an order where insertion
  and sorted order coincide. The test now filters on the later key.
* **M23** makes the verification treat a missing label key as satisfying the
  claim, which would let a partly-unlabelled cohort assert a restriction it does
  not meet - the same missing-key trap as M16, one layer up.
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
# PYTHONIOENCODING because the child encodes its own console output in cp1252 on
# this machine, and a mangled character must never turn a verdict into a crash.
ENV = {
    **os.environ,
    "PYTHONPATH": str(SRC / "src"),
    "PYTHONIOENCODING": "utf-8",
}

TESTS = ["tests/test_calibration_machinery.py"]

CAL = "src/hoops_gm/availability/calibration.py"
SYN = "src/hoops_gm/availability/calibration_synthetic.py"

MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "M01 provenance guard disabled (a restricted report may claim v2)",
        CAL,
        "        if self.restriction is not None and self.provenance is Provenance.PREREGISTERED_V2:",
        "        if False:",
    ),
    (
        "M02 Wilson interval loses its z^2/4n^2 term",
        CAL,
        "math.sqrt(p_hat * (1.0 - p_hat) / n + z * z / (4.0 * n * n))",
        "math.sqrt(p_hat * (1.0 - p_hat) / n)",
    ),
    (
        "M03 expected calibration error unweighted over bins",
        CAL,
        "    ece = sum(gap * count for gap, count in gaps) / total",
        "    ece = sum(gap for gap, _count in gaps) / len(gaps)",
    ),
    (
        "M04 calibration-in-the-large sign flipped",
        CAL,
        (
            "        return self.predicted_mean - self.observed_rate\n\n"
            "    @property\n"
            "    def bins_below_population_floor(self) -> tuple[str, ...]:"
        ),
        (
            "        return self.observed_rate - self.predicted_mean\n\n"
            "    @property\n"
            "    def bins_below_population_floor(self) -> tuple[str, ...]:"
        ),
    ),
    (
        "M05 monotonic reversal comparison flipped",
        CAL,
        "        if predicted_step * observed_step < 0:",
        "        if predicted_step * observed_step > 0:",
    ),
    (
        "M06 subgroup restriction widened from all to any",
        CAL,
        "        if all(row.labels.get(key) == value for key, value in wanted)",
        "        if any(row.labels.get(key) == value for key, value in wanted)",
    ),
    (
        "M07 distinct-probability grouping without the ulp rounding",
        CAL,
        "        grouped.setdefault(round(row.predicted, decimals), []).append(row)",
        "        grouped.setdefault(row.predicted, []).append(row)",
    ),
    (
        "M08 log-loss clips stop being counted",
        CAL,
        "            clipped += 1",
        "            pass  # mutated",
    ),
    (
        "M09 population floor check never fires",
        CAL,
        "            row.label for row in self.bins if row.observations < self.population_floor",
        "            row.label for row in self.bins if False",
    ),
    (
        "M10 emitted probability always declared inside its Wilson interval",
        CAL,
        "        return self.wilson_low <= self.predicted_mean <= self.wilson_high",
        "        return True",
    ),
    (
        "M11 exact_plays returns to banker's rounding",
        SYN,
        "    return min(observations, math.floor(observations * rate + 0.5))",
        "    return min(observations, round(observations * rate))",
    ),
    (
        "M12 band order inferred rather than declared",
        CAL,
        "    for label in order:",
        "    for label in sorted(order):",
    ),
    (
        "M13 an out-of-range injected error is clipped instead of refused",
        SYN,
        "        if not 0.0 <= predicted <= 1.0:",
        "        if False:",
    ),
    (
        "M14 final equal-width bin left half-open",
        CAL,
        "            f\"{']' if index == bin_count - 1 else ')'}\",",
        '            ")",',
    ),
    # M15-M18 are the four survivors from the independent review at 5032bf1.
    # They are here rather than only in the test file because a survivor that is
    # merely tested can be reintroduced by the next reader who treats the test as
    # optional; a mutation that goes red is a standing demonstration.
    (
        "M15 pre-filtered rows launder a restricted report as pooled v2 (review 3d)",
        CAL,
        "    inherited = _inherited_restriction(observations)",
        "    inherited: tuple[tuple[str, str], ...] = ()",
    ),
    (
        "M16 restrict() treats a missing label key as a match (review N02)",
        CAL,
        "        if all(row.labels.get(key) == value for key, value in wanted)",
        "        if all(row.labels.get(key, value) == value for key, value in wanted)",
    ),
    (
        "M17 Wilson z silently becomes the 90% constant (review N01)",
        CAL,
        "WILSON_Z_95: Final = 1.959963984540054",
        "WILSON_Z_95: Final = 1.6448536269514722",
    ),
    (
        "M18 bootstrap interval endpoints swapped (review N05)",
        CAL,
        (
            "        interval_low=type7_quantile(estimates, 0.025),\n"
            "        interval_high=type7_quantile(estimates, 0.975),"
        ),
        (
            "        interval_low=type7_quantile(estimates, 0.975),\n"
            "        interval_high=type7_quantile(estimates, 0.025),"
        ),
    ),
    # M19-M23 are the second review's findings, at 471c061. P11 is the one that
    # survived his own 11-mutation pass and is now M22; the rest pin the fixes
    # for the two payload lies and the container hardening.
    (
        "M19 nested restrict() drops the inherited pairs again (review P2-2)",
        CAL,
        (
            "    inherited = dict(_inherited_restriction(observations))\n"
            "    wanted = tuple(sorted((inherited | labels).items()))"
        ),
        "    wanted = tuple(sorted(labels.items()))",
    ),
    (
        "M20 a marker is trusted rather than verified against the rows (review P2-3)",
        CAL,
        "    _verify_restriction_holds(rows, merged)",
        "    pass",
    ),
    (
        "M21 slicing a restricted cohort returns a bare list again (review P2-1)",
        CAL,
        (
            "        if isinstance(index, slice):\n"
            "            return RestrictedCohort(super().__getitem__(index), self.restriction)"
        ),
        "        if False:\n            pass",
    ),
    (
        "M22 recorded_restriction left in insertion order (review P11, survived his pass)",
        CAL,
        "        tuple(sorted(merged.items())) if merged else None",
        "        tuple(merged.items()) if merged else None",
    ),
    (
        "M23 verification counts a missing key as satisfying the claim",
        CAL,
        "        offenders = sum(1 for row in rows if row.labels.get(key) != value)",
        "        offenders = sum(1 for row in rows if row.labels.get(key, value) != value)",
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
