"""Report the cohort generator's import closure against the fingerprints it publishes.

ADR-019 rules that the injury cohort manifest's fingerprint boundary is the
generator's **derivation closure** plus the store producers, and it publishes a
load-bearing number to justify that: *34 files in the closure, 3 fingerprinted*.

**That number had no way to be recounted.** It was measured once, by hand, on
2026-08-27 and written into an ADR. This repository's own header rule says a
derived number needs something that recounts it from the thing it describes -
`docs/backlog.md` has `backlog_graph.py`, `docs/handoff.md` has
`check_doc_terminators.py`, and ADR-019's closure count had nothing. This is
that. Run it and the ADR's claim is checkable in one command instead of
believed.

## What it compares

Three sets, because two of them have silently disagreed before:

- **closure** - every `hoops_gm` module reachable from the generator by
  `import` / `from ... import`, transitively, resolved to files on disk.
- **declared** - `DEFAULT_SOURCE_FINGERPRINT_PATHS` in the generator, read by
  parsing the source rather than importing it, so this script needs no
  `PYTHONPATH` and cannot be fooled by a stale installed copy of the package.
- **recorded** - the keys of `operator.source_fingerprints` in each committed
  manifest, which is the claim actually published to a reader.

`_source_fingerprints` in the generator carries the history for why the last two
are separate: a declared path that was dropped before being written left the two
sets disagreeing, and the test that checks fingerprints iterates the *recorded*
side, so it could not see the omission by construction.

## What it cannot tell you, which is the important half

**It sees `import` statements.** A module reached by a string name, an entry
point, a plugin lookup, a dynamic `importlib` call or a subprocess is invisible
to it. So the closure it reports is a **floor, not a count**, and a file absent
from it has not been shown to be irrelevant - only not to be imported.

It also says nothing about whether any fingerprint is *correct*, nothing about
whether a regeneration was authorised (see
`backend/tests/test_cohort_evidence.py` - the fingerprint check is green for
whoever ran it), and nothing about non-Python inputs.

## It reports; it does not gate

Exit is 0 whenever the closure could be computed, even with a gap outstanding.
The gap is real and currently large, and a gate that is red until it closes is a
gate everyone learns to ignore. Turning this into a failing test is the
`cohort-fingerprint-closure-check` backlog item's job, and that item's own
description carries the domain limit above so a green there is not read as
completeness.

## Usage

    python scripts/fingerprint_closure.py

"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "backend" / "src"
PACKAGE = "hoops_gm"
GENERATOR = PACKAGE_ROOT / PACKAGE / "ingest" / "injury_report" / "cohort_evidence.py"
DECLARED_NAME = "DEFAULT_SOURCE_FINGERPRINT_PATHS"
MANIFEST_DIR = REPO_ROOT / "docs" / "adapters"
MANIFEST_GLOB = "nba-injury-report-cohort-2*.json"


class ClosureError(RuntimeError):
    """The closure could not be computed, so no count may be reported."""


def _module_file(module: str) -> Path | None:
    """Resolve a dotted module to a file, preferring a package's __init__."""
    base = PACKAGE_ROOT / Path(*module.split("."))
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    candidate = base.with_suffix(".py")
    return candidate if candidate.is_file() else None


def _direct_imports(path: Path) -> set[str]:
    """Every ``hoops_gm`` module named by an import statement in one file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # `node.module` is None for a relative import; this package uses
            # absolute imports throughout, and a relative one would be a real
            # finding rather than something to resolve silently.
            if node.module and node.module.startswith(PACKAGE):
                found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith(PACKAGE))
    return found


def closure(root: Path) -> set[Path]:
    """Transitively resolve ``root``'s in-package imports to files on disk."""
    seen: set[str] = set()
    pending = list(_direct_imports(root))
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _module_file(module)
        if path is not None:
            pending.extend(_direct_imports(path))
    return {path for path in (_module_file(module) for module in seen) if path is not None}


def declared_paths(generator: Path) -> set[str]:
    """Read the declared fingerprint tuple by parsing, never by importing.

    Importing would need the package on `sys.path` and would happily read a
    stale installed copy instead of this checkout - the exact substitution this
    script exists to detect elsewhere.
    """
    tree = ast.parse(generator.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        targets: Iterable[ast.expr]
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = node.targets
        else:
            continue
        names = {t.id for t in targets if isinstance(t, ast.Name)}
        if DECLARED_NAME in names and node.value is not None:
            return set(ast.literal_eval(node.value))
    raise ClosureError(
        f"{DECLARED_NAME} was not found in {generator.name}. It was renamed or moved, "
        f"and reporting a closure gap against an empty declared set would invent one."
    )


def recorded_paths(manifest_dir: Path) -> dict[str, set[str]]:
    """The fingerprint keys each committed manifest actually publishes."""
    recorded: dict[str, set[str]] = {}
    for path in sorted(manifest_dir.glob(MANIFEST_GLOB)):
        document = json.loads(path.read_text(encoding="utf-8"))
        recorded[path.name] = set(document["operator"]["source_fingerprints"])
    return recorded


def _relative(path: Path) -> str:
    """Repo-relative path, or the absolute one when it is outside the tree.

    ``Path.relative_to`` raises for a path outside ``REPO_ROOT``, and the first
    caller of this function is the refusal that fires when the generator has
    moved. Raising there replaced a clean refusal with a ``ValueError`` from
    ``pathlib`` - **the refusal message was the thing that broke.** Found by
    ``test_an_absent_generator_refuses``, which is the reason that test asserts a
    refusal rather than trusting one.
    """
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def report(out: TextIO) -> int:
    if not GENERATOR.is_file():
        raise ClosureError(f"the generator is not at {_relative(GENERATOR)}; it moved")

    files = closure(GENERATOR)
    reached = {_relative(path) for path in files} - {_relative(GENERATOR)}
    declared = declared_paths(GENERATOR)
    unfingerprinted = sorted(reached - declared)
    # Store producers: declared because they wrote the persisted state, not
    # because the generator reads them. ADR-019 keeps these deliberately.
    producers = sorted(declared - reached - {_relative(GENERATOR)})

    print(f"generator            : {_relative(GENERATOR)}", file=out)
    print(f"direct in-package    : {len(_direct_imports(GENERATOR))} modules", file=out)
    print(f"transitive closure   : {len(reached)} files (a FLOOR - imports only)", file=out)
    print(f"declared fingerprints: {len(declared)} paths", file=out)
    print(f"  of which in closure: {len(declared) - len(producers) - 1}", file=out)
    print(f"  store producers    : {len(producers)}", file=out)
    print("  the generator      : 1", file=out)
    print(f"IN CLOSURE, NOT FINGERPRINTED: {len(unfingerprinted)}", file=out)
    for path in unfingerprinted:
        print(f"  - {path}", file=out)
    if producers:
        print("declared as store producers, not imported by the generator:", file=out)
        for path in producers:
            print(f"  + {path}", file=out)

    for name, keys in recorded_paths(MANIFEST_DIR).items():
        drift_missing = sorted(declared - keys)
        drift_extra = sorted(keys - declared)
        if drift_missing or drift_extra:
            state = (
                f"differs - declared-not-recorded {drift_missing}, "
                f"recorded-not-declared {drift_extra}"
            )
        else:
            state = "matches the declared set"
        print(f"manifest {name}: {len(keys)} recorded, {state}", file=out)

    print("", file=out)
    print(
        "A superseded manifest is SUPPOSED to differ: it describes the code that "
        "produced IT, not the code as it is today, and the registry in "
        "backend/tests/test_cohort_evidence.py is what says which those are. A live "
        "manifest differing is a real finding; a frozen one differing is provenance "
        "working.",
        file=out,
    )
    print(
        "This counts imports. A module reached by a string name, an entry point or a "
        "subprocess is invisible here, so the closure is a floor and an absent file "
        "has not been shown to be irrelevant. Reports only; the gate is "
        "cohort-fingerprint-closure-check.",
        file=out,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report the injury cohort generator's import closure against the fingerprints "
            "it declares and publishes. Recounts ADR-019's claim. Reports; does not gate."
        )
    )
    parser.parse_args(argv)
    try:
        return report(sys.stdout)
    except ClosureError as exc:
        print(f"refusing to report a count: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
