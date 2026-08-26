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

It compares **`test_*` function names only**, in **Python files only**, under
one path. Invisible to it:

* a deleted fixture, helper, or module-level constant;
* a deleted `assert` **inside** a surviving test, which is the most likely way
  a test quietly stops testing anything;
* a test that survives by name and has had its body gutted;
* a whole test file deleted **and** its name removed from the comparison scope,
  if you pass a narrowed `--path`;
* **the entire frontend suite.** `frontend/src/**/*.test.tsx` is vitest, not
  pytest: the names are `it(...)` and `describe(...)` strings rather than
  `def test_*`, and the files are not `.py`, so neither the parser nor the file
  walk can reach them. A change that adds or deletes vitest tests is invisible
  here **whatever `--path` you pass**;
* anything at all in `backend/src`.

**The default scope is itself a narrowing, and nobody passed it.** `--path`
defaults to `backend/tests`. Point this tool at a change that touches only the
frontend and it reports, truthfully, that nothing was dropped from a directory
you did not modify — and that reads as confirmation. That inversion is the
dangerous one: a wrong *base* produces an alarming `DROPPED` list that gets
investigated, while a right base with the wrong *scope* produces a clean report
covering nothing you changed, and a clean report ends the investigation. So the
scope is named in the success sentence rather than only in a parenthetical, and
changed files that look like tests and lie outside it are listed as **unread**.

So a clean report here means *no test function disappeared by name, in Python,
under this path*. It does not mean the suite still checks what it used to, and
it must not be quoted as though it did. Pair it with a count you predicted
before the change: the two answer different questions and neither substitutes
for the other.

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

#: Substrings that mark a path as somebody's test file, across the three
#: conventions this repository actually uses: pytest's `test_*.py`, vitest's
#: `*.test.ts`/`*.test.tsx`, and the `*.spec.*` form that arrives with copied
#: examples. Deliberately a crude match on the *name*, because the alternative
#: is parsing files this tool has already said it cannot parse - and a
#: false positive here costs one line of output, while a false negative
#: restores exactly the silence being fixed.
TEST_FILE_MARKERS = ("test_", "_test.", ".test.", ".spec.", "tests/")


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


def _changed_files(base: str, ref: str | None) -> list[str]:
    """Repo-relative paths that differ between ``base`` and ``ref``.

    When ``ref`` is ``None`` the comparison is against the working tree, so
    untracked files are included too: a brand-new test file is precisely the
    case where "you did not read this" is worth saying, and `git diff` alone
    would not mention it.
    """
    changed = set(
        _run("git", "diff", "--name-only", base, *([ref] if ref else [])).decode().split()
    )
    if ref is None:
        changed |= set(_run("git", "ls-files", "--others", "--exclude-standard").decode().split())
    return sorted(changed)


def _unread_test_files(changed: list[str], path: str) -> list[str]:
    """Changed files that look like tests and lie outside the comparison scope."""
    scope = path.rstrip("/") + "/"
    return [
        rel
        for rel in changed
        if not rel.startswith(scope) and any(mark in rel for mark in TEST_FILE_MARKERS)
    ]


def _report_unread(base: str, ref: str | None, path: str) -> None:
    """Name what the comparison did not look at, in the units it was not looking in.

    Without this the tool is silent about its own scope in exactly the case
    where the scope is the whole story: a change that touches only
    `frontend/src` gets a truthful, complete, useless all-clear about
    `backend/tests`.

    Reporting only - it never changes the exit code. Deciding whether an unread
    file matters is the same judgement that made this a script rather than a
    gate.
    """
    try:
        changed = _changed_files(base, ref)
    except subprocess.CalledProcessError:
        # A diff this tool could not take is worth one line, not a crash: the
        # name comparison above already succeeded and is still worth printing.
        print(f"could not list the files changed since {base}; scope below is unchecked")
        return

    unread = _unread_test_files(changed, path)
    if not unread:
        return

    print(f"NOT READ ({len(unread)}): changed files that look like tests, outside {path}:")
    for rel in unread:
        print(f"  ? {rel}")
    print()
    print(f"This tool parses `def test_*` in .py files under {path} and nothing else.")
    print("The files above changed and were not examined. If your change is a")
    print("frontend one, a clean report above is a statement about a directory")
    print("you did not touch.")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", help="the ref to compare against, e.g. a merge base")
    parser.add_argument("ref", nargs="?", default=None, help="default: the working tree")
    parser.add_argument("--path", default=DEFAULT_PATH, help=f"default: {DEFAULT_PATH}")
    args = parser.parse_args(argv)

    try:
        before = _names_at_ref(args.base, args.path)
        after = (
            _names_in_worktree(args.path)
            if args.ref is None
            else _names_at_ref(args.ref, args.path)
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
        print()
        _report_unread(args.base, args.ref, args.path)
        return 1

    # The scope belongs in the sentence, not only in the parenthetical above.
    # "No change to the set of test names" is true of a directory the reader may
    # not have touched, and read without its scope it is an all-clear over
    # nothing.
    if not added:
        print(f"No change to the set of test names in {args.path}.")
    else:
        print(f"Nothing dropped in {args.path}.")
    print()
    _report_unread(args.base, args.ref, args.path)
    print("Names only. A gutted test body, a deleted assertion inside a surviving")
    print("test, and a deleted fixture are all invisible here - see the docstring.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
