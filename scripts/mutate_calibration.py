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

**M24-M30 came from the reviewer's third pass.** Four of them (M24, M25, M26,
M27) are mutations he wrote that **survived** a suite which had just caught
twenty-three, and they share a shape worth naming: *each fix landed correctly on
the case that was driven and left the generalisation of that case untested.*
M19's fix made two-pair markers the normal case, and M24 shows the two-pair
verification path had never been exercised. M21's fix added four container
overrides, and M26 shows their **contents** were never asserted, only their type
and their marker. The rule he drew from it - **when a fix introduces a new
dimension, a second pair, a count, a precedence, write the test at n=2 rather
than n=1** - is the useful output of this pass.

* **M24** checks only the first recorded pair. Sorted order puts `band` before
  `status`, so a cohort that satisfies the first completely and the second not at
  all records 3,046 rows that `out` dominates 2,963 to 83 as `status=doubtful`.
* **M25** reverses `restrict()`'s key-conflict precedence, so asking for `out`
  after `doubtful` returns 83 `doubtful` rows labelled `out`. The marker stays
  self-consistent, so verification passes: **soundness is not identity.**
* **M26** drops the repeat count, losing rows silently while every type and
  marker assertion still holds.
* **M27** reverses the per-bin gap's declared sign. It survived because every
  consumer takes `abs()` - the second instance of the M12 symmetry class, and
  the general rule is that a declared convention is pinned only if some test
  observes it through a path that does not symmetrise it.
* **M28, M29 and M30** restore the over-wide re-wrap rule that the same pass
  showed was wrong: they let duplication, truncation and concatenation carry the
  marker forward. Verification cannot see it, because every row present still
  satisfies every recorded pair - the marker is true and the payload is false
  about the cohort. It bites arithmetically: condition 5 is a Wilson half-width
  going as 1/sqrt(n), so duplicating the 83-row `doubtful` cohort takes its worst
  case from 0.1052 to 0.0752 and converts "no 0.10 guarantee can be issued" into
  "protected".

**M31-M40 came from the reviewer's fourth pass**, which found **seven**
survivors against a suite that had just caught thirty - the sequence is
4, 5, 4, 7, and it is not converging. The pass produced two findings of a kind
the earlier ones did not.

The first is a **false guarantee** rather than a disclosed residual. Both
docstrings promised that multiplicity-changing operations return a plain `list`;
`rc += list(rc)`, `rc.extend(list(rc))` and `rc[0:0] = list(rc)` all returned a
`RestrictedCohort` with the marker intact and `n` doubled, because `__iadd__`
and the mutating methods have no override. Checking his payloads found two more
routes he had not listed - `append` and `insert` of a row taken *from the cohort
itself*, which he had recorded as "correctly refused" because he tried them with
a **foreign** row - and one payload of his that is simply **false**: `rc *= 2`
returns a plain `list`, because defining `__mul__` at Python level makes
`PyNumber_InPlaceMultiply` fall back to it. That route is closed by accident,
and an accident nothing records is not a guard.

So the repair is not a longer list of dunders. Duplication is refused where the
cohort becomes a number, by `_verify_no_duplicate_observations`, which does not
care how the rows arrived - covering direct construction and the adversarial
`__index__` that no container guard can see.

The second is a **declared convention the code did not implement**:
`DECLARED_CONVENTIONS["bootstrap_unit"]` said "one observation id, resampled
with replacement" while the loop resampled row *positions* and never read
`observation_id`. That is worse than an undeclared convention, because a later
reader has a written assurance and no reason to check it. `bootstrap_quantile`
was declared and pinned by nothing at all.

* **M31 and M32** remove the duplicate-observation check, and then relax it to
  ignore a single repeated id - the n=1 boundary of the *count*, applying the
  rule the third pass produced to the fix the fourth pass forced.
* **M33** lets verification tolerate exactly one violating row. Every cohort
  that reached verification carried dozens, so the boundary was never driven.
* **M34** compares label values by identity. It survives on a suite built from
  literals, because every literal is interned, and would spuriously refuse a
  correct cohort whose labels came from a database row.
* **M35, M36 and M37** are the third pass's re-wrap rule attacked at its
  untested edges: an operand that is neither empty nor `self`, an explicit
  step-1 *partial* slice, and a zero or negative repeat count.
* **M38, M39 and M40** cover the bootstrap. M38 accepts repeated ids again, M39
  swaps Hyndman-Fan type 7 for the floor rule - which is not an equivalent
  mutant, because it moves `interval_high` downward and `candidate_beats_baseline`
  reads `interval_high` - and M40 reverts the declaration while leaving the
  behaviour, which is the defect that started this group.
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
            "            if index.indices(len(self)) == (0, len(self), 1):\n"
            "                return RestrictedCohort(rows, self.restriction)"
        ),
        "            if False:\n                pass",
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
    (
        "M24 verification checks only the first recorded pair (review 3-A, survived)",
        CAL,
        "    for key, value in restriction.items():",
        "    for key, value in list(restriction.items())[:1]:",
    ),
    (
        "M25 restrict() lets the inherited pair win a key conflict (review 3-D, survived)",
        CAL,
        "    wanted = tuple(sorted((inherited | labels).items()))",
        "    wanted = tuple(sorted((labels | inherited).items()))",
    ),
    (
        "M26 __mul__ silently drops the repeat count (review 3-C, survived)",
        CAL,
        "        repeated: list[CalibrationObservation] = super().__mul__(count)",
        "        repeated: list[CalibrationObservation] = super().__mul__(1)",
    ),
    (
        "M27 per-bin gap sign reversed (review 3-E, survived: every consumer takes abs)",
        CAL,
        (
            "        through a path that does not symmetrise it.\n"
            '        """\n'
            "\n"
            "        return self.predicted_mean - self.observed_rate"
        ),
        (
            "        through a path that does not symmetrise it.\n"
            '        """\n'
            "\n"
            "        return self.observed_rate - self.predicted_mean"
        ),
    ),
    (
        "M28 __mul__ re-wraps at any count, so duplication keeps the marker (review 3-B)",
        CAL,
        (
            "        repeated: list[CalibrationObservation] = super().__mul__(count)\n"
            "        if count.__index__() == 1:"
        ),
        (
            "        repeated: list[CalibrationObservation] = super().__mul__(count)\n"
            "        if True:"
        ),
    ),
    (
        "M29 a partial slice re-wraps, so truncation keeps the marker (review 3-B)",
        CAL,
        "            if index.indices(len(self)) == (0, len(self), 1):",
        "            if True:",
    ),
    (
        "M30 __add__ re-wraps against a non-empty other, so concatenation keeps it (review 3-B)",
        CAL,
        (
            "        combined: list[CalibrationObservation] = super().__add__(other)\n"
            "        if not other:"
        ),
        (
            "        combined: list[CalibrationObservation] = super().__add__(other)\n"
            "        if True:"
        ),
    ),
    (
        "M31 the duplicate-observation check is removed entirely (review P4-1)",
        CAL,
        "    _verify_no_duplicate_observations(rows)",
        "    pass  # mutation: multiplicity unchecked",
    ),
    (
        "M32 the duplicate check ignores a single repeated id (review P4-1, n=1 boundary)",
        CAL,
        "if count > 1)",
        "if count > 2)",
    ),
    (
        "M33 verification tolerates exactly one violating row (review P4-4)",
        CAL,
        "        if offenders:",
        "        if offenders > 1:",
    ),
    (
        "M34 label values are compared by identity, not equality (review P4-8)",
        CAL,
        "row.labels.get(key) != value",
        "row.labels.get(key) is not value",
    ),
    (
        "M35 __add__ re-wraps unless other IS self, so concatenation keeps it (review P4-5)",
        CAL,
        (
            "        combined: list[CalibrationObservation] = super().__add__(other)\n"
            "        if not other:"
        ),
        (
            "        combined: list[CalibrationObservation] = super().__add__(other)\n"
            "        if other is not self:"
        ),
    ),
    (
        "M36 an explicit step-1 partial slice re-wraps, so truncation keeps it (review P4-6)",
        CAL,
        "            if index.indices(len(self)) == (0, len(self), 1):",
        "            if index.indices(len(self)) == (0, len(self), 1) or index.step == 1:",
    ),
    (
        "M37 __mul__ re-wraps at count <= 1, so an empty cohort keeps the marker (review P4-7)",
        CAL,
        (
            "        repeated: list[CalibrationObservation] = super().__mul__(count)\n"
            "        if count.__index__() == 1:"
        ),
        (
            "        repeated: list[CalibrationObservation] = super().__mul__(count)\n"
            "        if count.__index__() <= 1:"
        ),
    ),
    (
        "M38 the bootstrap accepts repeated observation ids again (review P4-2)",
        CAL,
        "    if repeated_ids:",
        "    if False:",
    ),
    (
        "M39 the bootstrap quantile becomes the floor rule, moving interval_high (review P4-3)",
        CAL,
        (
            "        interval_low=type7_quantile(estimates, 0.025),\n"
            "        interval_high=type7_quantile(estimates, 0.975),"
        ),
        (
            "        interval_low=sorted(estimates)[math.floor(0.025 * (len(estimates) - 1))],\n"
            "        interval_high=sorted(estimates)[math.floor(0.975 * (len(estimates) - 1))],"
        ),
    ),
    (
        "M40 the declared bootstrap unit stops mentioning the enforcement (review P4-2)",
        CAL,
        '        "one observation id, resampled with replacement; duplicate ids are refused"',
        '        "one observation id, resampled with replacement"',
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
