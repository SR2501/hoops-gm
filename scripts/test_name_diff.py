"""Report which `test_*` functions a change added and, more importantly, dropped.

**A recount of the finished thing agrees with itself perfectly after a
deletion.** That is why this exists and it is not hypothetical: on 2026-08-23 a
source-slice edit removed five test functions from one file - including
`test_every_engine_call_site_is_classified`, the census test that was the entire
point of the unit immediately preceding - and **every gate stayed green**.
`pytest` reported `1733 passed`, `ruff` passed, `mypy` passed. All three were
telling the truth about the tests that remained. Deleting a test breaks nothing.

The loss was caught only because someone had written down an expected count
beforehand and bothered to compare. This tool is that comparison, made cheap.

`docs/backlog.md` learned the identical lesson earlier and gained a slug-set
diff against the merge base. Test suites have the same hole. This is the same
check, pointed at a different artefact.

## Deliberately a script, not a gate

Nothing runs this automatically, by design. A CI gate on test-name sets is a
claim about CI shape and needs an owner who can answer *"what happens when a
test is legitimately renamed"* - and the honest answer is *it depends*, which a
gate cannot say. Here a rename simply shows as one dropped and one added, side
by side, and the operator decides in a second. That judgement is the whole
reason this is a tool you invoke rather than a rule you satisfy.

`scripts/mutate_aav.py` and `scripts/mutate_seed_demo.py` are the precedent.

## What it cannot see, which is most of what a file contains

It compares **`test_*` function names only**. Invisible to it:

* a deleted fixture, helper, or module-level constant;
* a deleted `assert` **inside** a surviving test, which is the most likely way
  a test quietly stops testing anything;
* a test that survives by name and has had its body gutted;
* a whole test file deleted **and** its name removed from the comparison scope,
  if you pass a narrowed `--path`;
* anything at all in `backend/src`.

So a clean report here means *no test function disappeared by name*. It does
not mean the suite still checks what it used to, and it must not be quoted as
though it did. Pair it with a count you predicted before the change: the two
answer different questions and neither substitutes for the other.

## Usage

    python scripts/test_name_diff.py <base> [ref]
    python scripts/test_name_diff.py "$(git merge-base HEAD origin/main)"
    python scripts/test_name_diff.py origin/main HEAD --path backend/tests

`ref` defaults to the working tree, which is the case that matters: it catches a
deletion *before* it is committed. Exits 1 if any name was dropped, 0 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DEFAULT_PATH = "backend/tests"


def _run(*args: str) -> bytes:
    return subprocess.run(args, cwd=REPO, check=True, capture_output=True).stdout


def _test_names(source: str) -> set[str]:
    """`test_*` function names in one module, including methods on test classes.

    Parsed rather than grepped. A grep for `def test_` also matches the string
    in this very docstring, and a scan that mistakes a description of a thing
    for the thing is the defect that put a fabricated entry into another
    register in this repository on 2026-08-23.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    }


def _names_at_ref(ref: str, path: str) -> set[str]:
    files = _run("git", "ls-tree", "-r", "--name-only", ref, "--", path).decode("utf-8").split()
    names: set[str] = set()
    for rel in files:
        if not rel.endswith(".py"):
            continue
        names |= _test_names(_run("git", "show", f"{ref}:{rel}").decode("utf-8"))
    return names


def _names_in_worktree(path: str) -> set[str]:
    names: set[str] = set()
    for file in sorted((REPO / path).rglob("*.py")):
        names |= _test_names(file.read_text(encoding="utf-8"))
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", help="the ref to compare against, e.g. a merge base")
    parser.add_argument("ref", nargs="?", default=None, help="default: the working tree")
    parser.add_argument("--path", default=DEFAULT_PATH, help=f"default: {DEFAULT_PATH}")
    args = parser.parse_args(argv)

    try:
        before = _names_at_ref(args.base, args.path)
        after = _names_in_worktree(args.path) if args.ref is None else _names_at_ref(
            args.ref, args.path
        )
    except subprocess.CalledProcessError as exc:
        print(exc.stderr.decode("utf-8", errors="replace").strip(), file=sys.stderr)
        return 2

    if not before:
        # An empty base is a broken comparison, not a clean one. Refusing here
        # is the same rule the census and the union predictor both follow: a
        # scan that found nothing has not told you that there is nothing.
        print(
            f"no test functions found at {args.base} under {args.path}. "
            f"The comparison would be vacuous, and every name would look 'added'. "
            f"Check the ref and the --path.",
            file=sys.stderr,
        )
        return 2

    dropped = sorted(before - after)
    added = sorted(after - before)
    where = args.ref or "working tree"

    print(f"base {args.base}: {len(before)}    {where}: {len(after)}    ({args.path})")
    print()
    if added:
        print(f"ADDED ({len(added)}):")
        for name in added:
            print(f"  + {name}")
        print()
    if dropped:
        print(f"DROPPED ({len(dropped)}):")
        for name in dropped:
            print(f"  - {name}")
        print()
        print("A dropped name is not automatically wrong - a rename appears here as")
        print("one dropped and one added, and only you can tell those apart. But a")
        print("deletion is invisible to every other check: the suite still passes,")
        print("because a test that is gone cannot fail.")
        return 1

    if not added:
        print("No change to the set of test names.")
    else:
        print("Nothing dropped.")
    print()
    print("Names only. A gutted test body, a deleted assertion inside a surviving")
    print("test, and a deleted fixture are all invisible here - see the docstring.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
