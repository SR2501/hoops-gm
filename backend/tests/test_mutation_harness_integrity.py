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

**What `scripts/` coverage actually is, stated carefully because the first
version of this paragraph was a false generalisation and an independent
reviewer caught it.** No CI job **lints or type-checks** `scripts/`, and
`mutate_calibration.py` specifically is **executed by no job** — which is what
makes the harness's own correctness depend on somebody remembering to run it,
and is the whole reason these tests exist. What is *not* true, and what the
earlier wording claimed, is that `scripts/` is untouched by CI: `ci.yml` runs
`scripts/backlog_graph.py` (line 142), `scripts/check_no_secrets.py` (354) and
`scripts/run_metrics.py` (93, 98, 292, 297) across four jobs. Nor is it true
that every Python job declares a working directory — `backlog-graph` and
`secrets` declare none. The narrow claim carries the design decision on its own;
the broad one was reached by generalising from the one job that had been read.

**Scope, stated so it is not over-read:** these tests establish that every anchor
still matches its target exactly once and that every replacement is a real
change. They do **not** run the mutations, do not establish that any mutation is
caught, and do not lint or type-check the harness. Its verdicts remain ungated.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

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
