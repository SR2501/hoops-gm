"""The provenance blast radius, pinned as a count rather than described in prose.

``record_refresh`` is idempotent on ``(artifact_type, artifact_key, version,
season)`` and, on the hit, performs ``existing.source = source`` in place. So a
scope that can receive two different source strings for the same content silently
loses the first label. That is an open defect in the primitive.

The primitive cannot tell a legitimate second producer from a relabel. **The call
sites can**, because a scope whose ``source`` argument is a compile-time constant
cannot receive a second value - not "does not today", *cannot*, without an edit.
That is a structural exclusion rather than an observation, and this module turns
it into something CI enforces.

That claim is only as strong as what counts as constant, and the first version of
this module got it wrong in two ways that an independent review demonstrated
rather than argued. It treated any attribute access as constant, so
``source=release.source_version`` - read out of a loaded artifact at runtime - was
classified constant and every test here reported green while a second scope
genuinely became multi-source. And it matched the literal identifier
``record_refresh``, so ``import record_refresh as _register`` made a call site
invisible; the vacuity floor did not help, because an aliased site adds zero.

Both are closed below, and the shape is worth carrying: **a checker that resolves
names loosely is not conservative, it is silently permissive.** Its failure mode is
a green result, which is the one nobody investigates.

At the time of writing exactly one call site passes a non-constant ``source``:
``import_schedule`` in ``ingest/importers.py``, parameterised so the reliability
publisher can label a derived schedule as derived. That parameterisation is what
made ``SCHEDULE``/``nba-schedule`` the only multi-source scope in the repository.

The point of a count is not the number. It is that the *next* expansion of the
blast radius has to be a deliberate, reviewed act - someone must come here and
change this test - instead of a one-word keyword argument nobody notices.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "hoops_gm"

# The one known variable-sourced call site, with the reason it is allowed to be one.
KNOWN_VARIABLE_SOURCED = {
    (
        "ingest/importers.py",
        "import_schedule takes source= so a derived schedule can be labelled derived; "
        "this is what made SCHEDULE/nba-schedule the only multi-source scope",
    )
}


def _module_level_constants(tree: ast.Module) -> set[str]:
    """Names bound exactly once at module level to a literal."""

    counts: dict[str, int] = {}
    literal: set[str] = set()
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        for target in targets:
            if isinstance(target, ast.Name):
                counts[target.id] = counts.get(target.id, 0) + 1
                if isinstance(value, ast.Constant):
                    literal.add(target.id)
    return {name for name in literal if counts[name] == 1}


def _source_is_constant(arg: ast.expr, constants: set[str]) -> bool:
    if isinstance(arg, ast.Constant):
        return True
    if isinstance(arg, ast.Name):
        return arg.id in constants
    # Nothing else counts. An earlier version returned True for any ``ast.Attribute``,
    # reasoning that ``SomeEnum.MEMBER`` is a constant - and an independent review
    # showed that is the module's own main false-green: ``source=release.source_version``
    # is an attribute, is read out of a loaded artifact at runtime, and sailed through
    # all ten tests while genuinely making a second scope multi-source. ``self.x``,
    # ``config.x``, ``parsed.x`` and ``args.x`` all spell it the same way.
    #
    # No call site passes an attribute today, so this costs nothing. If an enum-sourced
    # site ever appears, it should be added here deliberately - which is this module's
    # whole point.
    return False


def _record_refresh_bindings(tree: ast.Module) -> set[str]:
    """Local names bound to ``lineage.record_refresh`` in this module.

    Matching the literal identifier is not enough: ``from hoops_gm.db.lineage import
    record_refresh as _register`` makes a call site invisible to a name comparison, and
    the vacuity floor does not help because an aliased site adds zero to the count. A
    review demonstrated exactly that with a bare parameter as the source and all ten
    tests green.
    """

    names = {"record_refresh"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "hoops_gm.db.lineage":
            for alias in node.names:
                if alias.name == "record_refresh":
                    names.add(alias.asname or alias.name)
    return names


def _call_sites() -> list[tuple[str, int, str, bool]]:
    """Every record_refresh call in production code, with its resolved source."""

    sites: list[tuple[str, int, str, bool]] = []
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "record_refresh" not in text:
            continue
        tree = ast.parse(text)
        constants = _module_level_constants(tree)
        bindings = _record_refresh_bindings(tree)
        rel = path.relative_to(SRC).as_posix()
        called_here: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                matched = func.id in bindings
            else:
                matched = getattr(func, "attr", None) == "record_refresh"
            if not matched:
                continue
            called_here.add(id(func))
            source = next((k.value for k in node.keywords if k.arg == "source"), None)
            if source is None:
                # A positional or absent source is worse than a variable one:
                # nothing here can tell what it is. Fail loudly rather than skip.
                sites.append((rel, node.lineno, "<not a keyword argument>", False))
                continue
            sites.append(
                (rel, node.lineno, ast.unparse(source), _source_is_constant(source, constants))
            )

        # The primitive handed somewhere rather than called: functools.partial, a
        # decorator, a dict of writers. The source cannot be resolved from here, so it
        # is reported as non-constant rather than passed over in silence.
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in bindings and id(node) not in called_here:
                sites.append((rel, node.lineno, f"<{node.id} referenced, not called>", False))
    return sites


def test_the_walk_reaches_all_eight_known_call_sites() -> None:
    """The enumeration must find the sites it knows about, or everything below is vacuous.

    Name the defect the count test excludes: a second multi-source scope appearing
    unnoticed. Name the reading in which it passes and that defect is present: the
    walk matches nothing at all - a renamed primitive, a moved package, a changed
    call syntax - and ``0 <= 1`` trivially holds. This is the check that excludes
    that reading, and it is the reason the count test can be trusted.

    The floor is eight rather than one deliberately. A review pointed out that the
    earlier name said ``at_least_one`` while the assertion said ``>= 8`` - a name
    understating its own check, which is the mild inverse of the defect this file
    exists to catch, so the name moved rather than the assertion.
    """

    sites = _call_sites()
    assert len(sites) >= 8, f"expected the known call sites, walked up only {len(sites)}: {sites}"


def test_exactly_one_call_site_can_receive_more_than_one_source() -> None:
    """A second variable-sourced call site must be a deliberate act, not a keyword.

    If this fails because you added one, that is the test working. Decide whether
    the new scope can genuinely receive two different sources for the same content
    version - and if it can, the in-place relabel in ``record_refresh`` is now live
    for it too, which is an architect contract question and not a test to edit past.
    """

    variable_sourced = [site for site in _call_sites() if not site[3]]
    described = {
        (path, f"{path}:{line} passes source={expr}") for path, line, expr, _ in variable_sourced
    }
    known = {path for path, _ in KNOWN_VARIABLE_SOURCED}

    assert {path for path, _ in described} == known, (
        "the set of call sites able to receive two sources has changed.\n"
        f"  now: {sorted(described)}\n"
        f"  known: {sorted(KNOWN_VARIABLE_SOURCED)}"
    )
    assert len(variable_sourced) == 1, (
        f"expected exactly one variable-sourced call site, found {variable_sourced}"
    )


@pytest.mark.parametrize("path, line, expr, is_constant", _call_sites())
def test_every_other_call_site_passes_a_compile_time_constant(
    path: str, line: int, expr: str, is_constant: bool
) -> None:
    """Parameterised so a regression names the offending file and line itself.

    The bundled version of this assertion reported only the first failure, which
    on a walk over eight sites is the least useful half of the answer.
    """

    if path in {known for known, _ in KNOWN_VARIABLE_SOURCED}:
        pytest.skip(f"{path} is the known variable-sourced site")
    assert is_constant, (
        f"{path}:{line} passes source={expr}, which is not a compile-time constant. "
        "That scope can now receive two sources, and record_refresh relabels in place."
    )
