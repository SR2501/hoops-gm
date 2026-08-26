"""Anchor integrity for `scripts/mutate_calibration.py`.

**Why this is a separate file, which is load-bearing rather than tidiness.**
These tests were first written inside `test_calibration_machinery.py`, which is
the module the mutation harness runs. That is a trap: while a mutation is
applied, the mutated line no longer matches its own anchor, so the anchor test
fails — and the harness scores *any* failure as CAUGHT. Every mutation of
`calibration.py` would have been marked caught by these tests rather than by the
detector it was written to exercise, and the harness would have reported 44 of
44 while establishing nothing. Driven and confirmed before the split: with M02
applied, this file's anchor assertion fails with `anchor found 0 times`.

Living here, they never run under the harness (it runs one named module) and
still run in CI, which is the whole point — `scripts/` is linted, type-checked
and executed by **no** job in `.github/workflows/ci.yml`; every Python job
declares a working directory of `backend`, `frontend` or `userscript`. So the
harness's own correctness was gated by nothing but somebody remembering to run
it. That bit when `ruff format` turned out to be a real gate: formatting
`calibration.py` joined three lines and four anchors went stale.

**Scope, stated so it is not over-read:** these tests establish that every anchor
still matches its target exactly once and that every replacement is a real
change. They do **not** run the mutations, do not establish that any mutation is
caught, and do not lint or type-check the harness. Its verdicts remain ungated.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_MUTATION_HARNESS = _REPO_ROOT / "scripts" / "mutate_calibration.py"


def _harness_mutations() -> list[tuple[str, str, str, str]]:
    """Read `MUTATIONS` out of the harness by parsing it, never by importing it.

    Parsing keeps this test from executing a script whose whole job is to
    overwrite source files. The tuples reference module-level string constants
    (`CAL`, `TEST`, `SYN`) rather than repeating the paths, so those are
    resolved here; anything that is neither a string literal nor one of those
    names raises instead of being silently skipped, because a mutation this
    reader cannot resolve is a mutation this reader is not checking.
    """
    tree = ast.parse(_MUTATION_HARNESS.read_text(encoding="utf-8"))

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
    """`docs/models/injury-status-conversion.md` states 44 in two places.

    Pinned so the card cannot silently drift out of date: adding a mutation is
    meant to cost an edit here and an edit there. Names are checked distinct in
    the same test because the harness prints verdicts by name, and two
    mutations sharing one would make its report ambiguous rather than wrong —
    the quiet failure, not the loud one.
    """
    mutations = _harness_mutations()
    assert len(mutations) == 44
    names = [name for name, _relative, _old, _new in mutations]
    assert len(set(names)) == len(names), "two mutations share a name"
