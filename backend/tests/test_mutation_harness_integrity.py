"""Anchor integrity for `scripts/mutate_calibration.py`.

**Why this is a separate file, which is load-bearing rather than tidiness.**
These tests were first written inside `test_calibration_machinery.py`, which is
the module the mutation harness runs. That is a trap: while a mutation is
applied, the mutated line no longer matches its own anchor, so the anchor test
fails — and the harness scores *any* failure as CAUGHT. The anchor test would
have fired **in addition to** each mutation's real detector, not instead of it,
so what it destroys is **discriminative power** rather than the catches: since
every mutation does have a genuine detector, the printed output in that
counterfactual world would have been **byte-identical** to today's `44 caught,
0 survived`. Nothing would have looked wrong. The damage is prospective — the
next mutation added, or the next detector weakened, would have read as caught.
Driven and confirmed before the split: with M02 applied, this file's anchor
assertion fails with `anchor found 0 times`.

Living here, they never run under the harness (it runs one named module) and
still run in CI.

**What `scripts/` coverage actually is, stated carefully because this paragraph
has now been wrong twice.** The first version was a false generalisation and an
independent reviewer caught it. The correction narrowed the claim and kept a
false conjunct: it said no CI job **lints or type-checks** `scripts/`, and the
type-check half was already untrue when it was written. `backend/pyproject.toml`
sets `[tool.mypy] files = ["src", "tests", "../scripts"]` deliberately, with a
comment saying why, and `ci.yml`'s backend job runs a bare `mypy` — so
`scripts/` has been type-checked in CI all along. Driven rather than argued: a
deliberate `return "not an int"` planted in `scripts/predict_union.py` makes
that bare `mypy` report `..\\scripts\\predict_union.py:123: error` and fail,
across 201 source files.

As of 2026-08-26 the lint half is closed too: a repo-root `ruff.toml` extends the
backend rule set over `scripts/`, and the backend job runs `ruff check scripts`
and `ruff format --check scripts` from the repo root. `scripts/eslint.config.js`
covers the two JavaScript probes, which no gate reached at all.

What remains true, and is the reason these tests exist: **`mutate_calibration.py`
is executed by no job.** Its verdicts are ungated, so the harness's own
correctness still depends on somebody remembering to run it.

What was never true, and is worth keeping visible because the false version is
what a later reader inherits: that `scripts/` is untouched by CI. `ci.yml` runs
`scripts/backlog_graph.py` (line 142), `scripts/check_no_secrets.py` (354) and
`scripts/run_metrics.py` (93, 98, 292, 297) across four jobs. Nor is it true that
every Python job declares a working directory — `backlog-graph` and `secrets`
declare none.

**Scope, stated so it is not over-read:** the anchor tests here establish that
every anchor still matches its target exactly once and that every replacement is
a real change. They do **not** run the mutations and do not establish that any
mutation is caught. The catcher tests below establish that the harness reads its
own output correctly; they do not establish that any particular catcher is a
genuine detector, which is a reading rather than a measurement.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_MUTATION_HARNESS = _REPO_ROOT / "scripts" / "mutate_calibration.py"

#: Calls that can rebind a module-level name without any syntactic assignment
#: this reader could see. If the harness ever uses one, the honest answer is
#: that static resolution no longer establishes anything, not that it passed.
_OPAQUE_REBINDING = frozenset({"globals", "locals", "vars", "setattr", "exec", "eval"})


def _harness_mutations() -> list[tuple[str, str, str, str]]:
    """Read `MUTATIONS` out of the harness by parsing it, never by importing it.

    Parsing keeps this test from executing a script whose whole job is to
    overwrite source files. The tuples reference module-level string constants
    (`CAL`, `TEST`, `SYN`) rather than repeating the paths, so those are
    resolved here; anything that is neither a string literal nor one of those
    names raises instead of being silently skipped, because a mutation this
    reader cannot resolve is a mutation this reader is not checking.

    **Rebinding is refused by a predicate over one traversal, not by a list of
    statement forms.** The first version of this guard enumerated top-level
    `Assign`/`AnnAssign` with a `Name` target, and an independent reviewer walked
    four forms straight through it: a tuple unpack (`CAL, _U = SYN, 0`), a walrus
    (`_W = (CAL := SYN)`), a `globals()['CAL'] = SYN`, and an assignment nested in
    an `if`. In every one the reader validated 41 anchors against `calibration.py`
    while the harness would have targeted `calibration_synthetic.py` — the exact
    mis-resolution the guard was written to refuse, reported as 41 anchors
    present.

    **That is the finding worth carrying, and it is not about this function.**
    The author found the mundane form (a plain second assignment) before review
    and fixed *that form*; the reviewer's four siblings, one of which he had
    already driven, all survived. **A guard that works by enumerating syntactic
    forms is always one form behind.** So this counts every `ast.Name` store
    anywhere in the tree — `ast.walk` sees tuple targets, walrus targets, `for`
    targets, `with ... as`, comprehension targets and augmented assignment
    identically, because all of them are a `Name` with `ctx=Store` — and refuses
    any resolved name stored more than once. Forms nobody enumerated are covered
    because nothing is enumerated. It is the same repair as the pass-four dunder
    finding: check where the value is used, not at every route that could reach
    it.

    Dynamic rebinding has no `Name` store at all, so it is refused separately and
    bluntly: if the harness calls `globals`, `locals`, `vars`, `setattr`, `exec`
    or `eval` anywhere, static resolution no longer establishes anything, and the
    honest report is a failure rather than a pass.
    """
    tree = ast.parse(_MUTATION_HARNESS.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _OPAQUE_REBINDING
        ):
            raise AssertionError(
                f"{_MUTATION_HARNESS.name} calls {node.func.id}() at line {node.lineno}; "
                "a module that can rebind names dynamically cannot be resolved statically, "
                "and reporting success here would certify a check this reader did not perform"
            )
        # `MUTATIONS.append(...)`, `.extend(...)`, `.insert(...)` add entries with
        # no `Store` anywhere, so counting stores cannot see them. Any attribute
        # access on the name is refused; the harness legitimately makes none.
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "MUTATIONS"
        ):
            raise AssertionError(
                f"MUTATIONS.{node.attr} at line {node.lineno}: entries added or removed through "
                "an attribute are invisible to this reader, which would then check a subset "
                "of the mutations the harness runs and report every anchor present"
            )

    stores: Counter[str] = Counter(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    )
    if stores["MUTATIONS"] != 1:
        raise AssertionError(
            f"MUTATIONS is stored {stores['MUTATIONS']} times in {_MUTATION_HARNESS.name}; "
            "this reader reads one list literal and would miss every entry added elsewhere"
        )

    constants: dict[str, str] = {}
    mutations_node: ast.List | None = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets: list[ast.expr] = [node.target]
            value: ast.expr | None = node.value
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        else:
            continue
        if value is None:
            continue
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "MUTATIONS":
                if not isinstance(value, ast.List):
                    raise AssertionError("MUTATIONS is no longer a list literal")
                mutations_node = value
            elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                constants[target.id] = value.value

    if mutations_node is None:
        raise AssertionError(f"no MUTATIONS assignment found in {_MUTATION_HARNESS}")

    resolved: list[tuple[str, str, str, str]] = []
    for element in mutations_node.elts:
        if not isinstance(element, ast.Tuple):
            raise AssertionError("a MUTATIONS entry is not a tuple literal")
        fields: list[str] = []
        for item in element.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                fields.append(item.value)
            elif isinstance(item, ast.Name) and item.id in constants:
                if stores[item.id] != 1:
                    raise AssertionError(
                        f"{item.id} is stored {stores[item.id]} times in {_MUTATION_HARNESS.name}; "
                        "this reader would resolve it to one value while Python used "
                        "the one in force at the MUTATIONS literal"
                    )
                fields.append(constants[item.id])
            else:
                raise AssertionError(
                    f"unresolvable MUTATIONS field at line {item.lineno}; this reader "
                    "would otherwise skip a mutation it cannot see"
                )
        if len(fields) != 4:
            raise AssertionError(f"a MUTATIONS entry has {len(fields)} fields, expected 4")
        resolved.append((fields[0], fields[1], fields[2], fields[3]))
    return resolved


def test_the_mutation_harness_is_where_this_module_expects_it() -> None:
    """Fail loudly rather than skip.

    A `pytest.skip` when the harness is missing would make every assertion below
    vacuous in exactly the situation they exist for — the file moved or was
    deleted — and a green skip reads as a pass in the summary line.
    """
    assert _MUTATION_HARNESS.is_file(), f"mutation harness not found at {_MUTATION_HARNESS}"


def test_every_mutation_anchor_still_matches_its_target_exactly_once() -> None:
    """The check that `ruff format` broke, now inside the gate.

    Reported per anchor rather than as a count, because the useful output when
    this fails is *which* anchor went stale — the repair is to re-extract the
    line as the formatter now writes it, not to guess at it.
    """
    stale: list[str] = []
    for name, relative, old, _new in _harness_mutations():
        target = _BACKEND_ROOT / relative
        assert target.is_file(), f"[{name}] targets a file that does not exist: {target}"
        found = target.read_text(encoding="utf-8").count(old)
        if found != 1:
            stale.append(f"[{name}] anchor found {found} times in {relative}, expected 1")
    assert not stale, "\n".join(stale)


def test_every_mutation_replacement_actually_changes_the_source() -> None:
    """A replacement equal to its anchor is a mutation that runs and proves nothing.

    The harness detects this too, but only after writing the file and re-reading
    it; here it is a text comparison, so a no-op mutation cannot reach the point
    of costing a full suite run to discover.
    """
    for name, _relative, old, new in _harness_mutations():
        assert new != old, f"[{name}] replacement is identical to its anchor"


def test_the_mutation_count_the_model_card_cites_is_pinned_here() -> None:
    """`docs/models/injury-status-conversion.md` states the count in two places.

    Pinned so the card cannot silently drift out of date: adding a mutation is
    meant to cost an edit here and an edit there. Names are checked distinct in
    the same test because the harness prints verdicts by name, and two
    mutations sharing one would make its report ambiguous rather than wrong —
    the quiet failure, not the loud one.

    **The count on its own is not load-bearing, which a reviewer established by
    driving it rather than by arguing it.** He substituted one mutation's tuple
    for a copy of another's under a fresh name: the count is untouched, the names
    are distinct, every anchor is unique and every replacement differs, so all
    four assertions here passed while a real detector had been deleted and
    replaced by a duplicate of its neighbour. A count cannot see a substitution.
    So the *content* is pinned too — the `(file, anchor, replacement)` triples
    must be distinct, which is the property the count was being asked to stand in
    for. Two mutations doing the same thing under different names is exactly the
    shape of a detector quietly removed.
    """
    mutations = _harness_mutations()
    assert len(mutations) == 55
    names = [name for name, _relative, _old, _new in mutations]
    assert len(set(names)) == len(names), "two mutations share a name"
    corruptions = [(relative, old, new) for _name, relative, old, new in mutations]
    assert len(set(corruptions)) == len(corruptions), (
        "two mutations apply the same corruption to the same file under different "
        "names; the count and the names both survive that, so a detector can be "
        "replaced by a duplicate of another with nothing here noticing"
    )


# --- The catcher report ------------------------------------------------------
#
# `55 caught, 0 survived` says every mutation was detected. It does not say **by
# what**, and the difference is the whole of handoff #9's near-miss: an anchor
# test inside the module the harness runs fires on every mutation *alongside* the
# real detector, so the printed output stays byte-identical to a healthy one
# while discriminating nothing.
#
# The harness now reads the failing test names out of output it already produced,
# on every run. These tests cover the reading. They are here rather than in
# `test_calibration_machinery.py` for the reason this whole file exists.


@pytest.fixture(scope="module")
def harness() -> ModuleType:
    """Import the harness for its pure functions.

    **Importing is safe and is checked rather than assumed** - see
    `test_the_harness_does_nothing_destructive_at_import_time` below. The anchor
    reader above still parses instead, because it has to work on a harness that
    is broken; these tests exercise functions, which requires the real ones.
    """
    spec = importlib.util.spec_from_file_location("mutate_calibration", _MUTATION_HARNESS)
    assert spec and spec.loader, f"cannot load {_MUTATION_HARNESS}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: A real `pytest` short-summary block, recorded from this repository's own
#: `backend` with the exact arguments the harness passes - not invented, because
#: a fixture written from memory tests the memory. Note the parametrised test:
#: **four** `FAILED` lines for **three** functions.
_RECORDED_SUMMARY = """\
=========================== short test summary info ===========================
FAILED tests/_tmp_catcher_probe.py::test_control_fails_one - assert 1 == 2
FAILED tests/_tmp_catcher_probe.py::test_control_fails_two - ValueError: boom
FAILED tests/_tmp_catcher_probe.py::test_control_parametrised[1] - assert 1 =...
FAILED tests/_tmp_catcher_probe.py::test_control_parametrised[2] - assert 2 =...
4 failed, 1 passed in 0.16s
"""

_RECORDED_GREEN = "131 passed in 12.02s\n"


def test_the_harness_does_nothing_destructive_at_import_time(harness: ModuleType) -> None:
    """The precondition for the fixture above, driven rather than believed.

    This module's whole job is overwriting source files in place. Importing it
    is only acceptable while every destructive path sits behind the
    `if __name__ == "__main__"` guard, so that is asserted here rather than
    left as a comment somebody later invalidates.
    """
    tree = ast.parse(_MUTATION_HARNESS.read_text(encoding="utf-8"))
    top_level_calls = [
        node
        for node in tree.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
    ]

    assert not top_level_calls, (
        "the harness makes a call at module scope; importing it would run that, "
        "and this module writes to source files"
    )
    assert harness.MUTATIONS, "importing the harness produced no mutations"


def test_failed_lines_are_read_as_node_ids(harness: ModuleType) -> None:
    assert harness.failed_nodeids(_RECORDED_SUMMARY) == [
        "tests/_tmp_catcher_probe.py::test_control_fails_one",
        "tests/_tmp_catcher_probe.py::test_control_fails_two",
        "tests/_tmp_catcher_probe.py::test_control_parametrised[1]",
        "tests/_tmp_catcher_probe.py::test_control_parametrised[2]",
    ]


def test_catchers_are_counted_per_function_not_per_parametrised_case(
    harness: ModuleType,
) -> None:
    """Four `FAILED` lines, three catchers, and the difference is load-bearing.

    The unit of pinning has to be the unit of *deletion*. A mutation caught by
    three cases of one parametrised test is pinned by one test, not three:
    delete that function and the mutation is unpinned completely. The target
    module has seven parametrised tests, so counting node ids would understate
    single-pinning on real data rather than on a hypothetical.
    """
    catchers = harness.catcher_functions(harness.failed_nodeids(_RECORDED_SUMMARY))

    assert catchers == {
        "test_control_fails_one",
        "test_control_fails_two",
        "test_control_parametrised",
    }


def test_a_class_nested_node_id_reduces_to_the_function(harness: ModuleType) -> None:
    assert harness.catcher_functions(["tests/x.py::TestGroup::test_y[case-3]"]) == {"test_y"}


def test_the_extractor_agrees_with_pytests_own_count(harness: ModuleType) -> None:
    """The control that runs on every mutation, driven here on a known input."""
    assert len(harness.failed_nodeids(_RECORDED_SUMMARY)) == harness.reported_failures(
        _RECORDED_SUMMARY
    )


def test_the_extractor_control_can_actually_fail(harness: ModuleType) -> None:
    """A control never seen to fire is not a control.

    A parsed zero and a genuinely uncaught mutation are indistinguishable in the
    output, and this repository produced four false zeros in one day from
    trusting one. So the disagreement case is driven: drop a `FAILED` line and
    keep the total, which is exactly the shape of a parser that has fallen
    behind pytest's format.
    """
    doctored = _RECORDED_SUMMARY.replace(
        "FAILED tests/_tmp_catcher_probe.py::test_control_fails_one - assert 1 == 2\n", ""
    )

    assert len(harness.failed_nodeids(doctored)) == 3
    assert harness.reported_failures(doctored) == 4
    assert len(harness.failed_nodeids(doctored)) != harness.reported_failures(doctored)


def test_a_green_run_yields_no_catchers_and_no_count(harness: ModuleType) -> None:
    """The negative control on the same extractor, on output with no failures."""
    assert harness.failed_nodeids(_RECORDED_GREEN) == []
    assert harness.reported_failures(_RECORDED_GREEN) is None


def test_the_child_arguments_cannot_depend_on_what_is_being_reported(
    harness: ModuleType,
) -> None:
    """ "The reporting path cannot alter a verdict" made checkable.

    The catcher report reads output the child already produced. That claim holds
    only while the child's arguments are fixed, so `pytest_argv` is the single
    place they are built, it takes only the test paths, and nothing in it is
    conditional. A flag added here on a `--catchers` branch would make a verdict
    depend on whether the detail was printed.
    """
    tree = ast.parse(_MUTATION_HARNESS.read_text(encoding="utf-8"))
    built = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "pytest_argv"
    ]
    assert len(built) == 1, "pytest_argv is the one place the child's argv is built"

    signature = built[0].args
    assert [arg.arg for arg in signature.args] == ["tests"], (
        "pytest_argv must take the test paths and nothing else; an option "
        "parameter is how a reporting flag reaches the child"
    )
    assert not any(isinstance(node, ast.If | ast.IfExp) for node in ast.walk(built[0])), (
        "no argument may be conditional, or the argv stops being fixed"
    )


def test_the_harness_never_adds_a_second_quiet_flag(harness: ModuleType) -> None:
    """`-qq` exits 0 while deleting the `N passed` line the baseline check reads.

    `backend/pyproject.toml` already sets `-q` in `addopts`, so one more from
    here is `-qq` - and the harness refuses to mutate unless it can parse
    `N passed` from a green baseline. It would then refuse every time, which is
    at least loud; the worse reading is a future edit that also relaxes the
    baseline check.
    """
    argv = harness.pytest_argv(["tests/test_calibration_machinery.py"])

    assert "-q" not in argv and "-qq" not in argv
    assert argv[1:3] == ["-m", "pytest"]
    assert "tests/test_calibration_machinery.py" in argv


def test_the_report_survives_a_run_that_caught_nothing(harness: ModuleType) -> None:
    """An empty report must say so rather than raising on `most_common(1)[0]`.

    Reachable in the case that matters most - every mutation surviving - where
    an exception would replace the finding with a traceback.
    """
    harness.report_catchers({}, detail=True)
