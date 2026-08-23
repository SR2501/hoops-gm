"""The test-name diff, and the deletion that every other gate reported as green.

The regression under test is not a crash. On 2026-08-23 a source-slice edit
removed five `test_*` functions from one file, and `pytest`, `ruff` and `mypy`
all passed - truthfully, because a test that is gone cannot fail.
`test_a_deletion_is_reported_where_a_count_would_not_be` reproduces exactly that
shape: a suite that loses one test and gains two, so its *total goes up* while
something load-bearing is missing.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "test_name_diff.py"
REAL_TESTS = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def differ() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_name_diff", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- parsing -----------------------------------------------------------------


def test_it_finds_plain_functions_and_methods_on_classes(differ: ModuleType) -> None:
    source = (
        "def test_alpha() -> None: ...\n"
        "def helper() -> None: ...\n"
        "class TestGroup:\n"
        "    def test_beta(self) -> None: ...\n"
        "    def setup_method(self) -> None: ...\n"
        "async def test_gamma() -> None: ...\n"
    )

    assert differ._test_names(source) == {"test_alpha", "test_beta", "test_gamma"}


def test_prose_about_a_test_is_not_counted_as_a_test(differ: ModuleType) -> None:
    """Parsed, not grepped - a description is not the thing described.

    A grep for `def test_` matches this docstring. That failure mode is not
    hypothetical here: a literal-string scan elsewhere in this repository put a
    fabricated entry into an audit register because a module's docstring
    honestly spelled out the call it made.
    """
    source = '"""This module would define def test_ghost() if it did anything."""\nVALUE = 1\n'

    assert differ._test_names(source) == set()


def test_an_unparseable_file_yields_nothing_rather_than_crashing(differ: ModuleType) -> None:
    assert differ._test_names("def test_broken(:\n") == set()


# --- the incident ------------------------------------------------------------


def test_a_deletion_is_reported_where_a_count_would_not_be(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], differ: ModuleType
) -> None:
    """The 2026-08-23 shape: total rises while a load-bearing test disappears.

    One test deleted, two added. Any check that compares totals sees `2 -> 3`
    and reports growth. Only the set difference sees the loss.
    """
    repo = _repo_with_tests(
        tmp_path,
        before="def test_kept() -> None: ...\ndef test_load_bearing() -> None: ...\n",
        after=(
            "def test_kept() -> None: ...\n"
            "def test_new_one() -> None: ...\n"
            "def test_new_two() -> None: ...\n"
        ),
    )

    exit_code = _run_in(repo, ["HEAD~1", "HEAD", "--path", "tests"], differ)
    out = capsys.readouterr().out

    assert exit_code == 1, "a dropped test name must be a non-zero exit"
    assert "test_load_bearing" in out
    assert "DROPPED (1)" in out
    # The count went UP, which is exactly why a count cannot be trusted here.
    assert "2 " in out and "3 " in out
    assert "ADDED (2)" in out


def test_a_pure_addition_is_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], differ: ModuleType
) -> None:
    repo = _repo_with_tests(
        tmp_path,
        before="def test_kept() -> None: ...\n",
        after="def test_kept() -> None: ...\ndef test_added() -> None: ...\n",
    )

    exit_code = _run_in(repo, ["HEAD~1", "HEAD", "--path", "tests"], differ)

    assert exit_code == 0
    assert "Nothing dropped." in capsys.readouterr().out


def test_a_rename_is_shown_as_both_halves_rather_than_judged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], differ: ModuleType
) -> None:
    """The case that made this a script rather than a gate.

    A gate would have to decide whether this is a loss. It cannot. The tool
    shows both halves side by side and the operator decides in a second - which
    is precisely the judgement that blocked making this automatic.
    """
    repo = _repo_with_tests(
        tmp_path,
        before="def test_old_name() -> None: ...\n",
        after="def test_new_name() -> None: ...\n",
    )

    exit_code = _run_in(repo, ["HEAD~1", "HEAD", "--path", "tests"], differ)
    out = capsys.readouterr().out

    assert exit_code == 1, "a rename exits non-zero on purpose: a human should look"
    assert "- test_old_name" in out
    assert "+ test_new_name" in out
    assert "a rename appears here as" in out


def test_it_compares_the_working_tree_when_no_ref_is_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], differ: ModuleType
) -> None:
    """The case that matters most: catching a deletion before it is committed."""
    repo = _repo_with_tests(
        tmp_path,
        before="def test_kept() -> None: ...\ndef test_doomed() -> None: ...\n",
        after="def test_kept() -> None: ...\ndef test_doomed() -> None: ...\n",
    )
    (repo / "tests" / "test_sample.py").write_text("def test_kept() -> None: ...\n", "utf-8")

    exit_code = _run_in(repo, ["HEAD", "--path", "tests"], differ)

    assert exit_code == 1
    assert "test_doomed" in capsys.readouterr().out


# --- refusals ----------------------------------------------------------------


def test_an_empty_base_is_refused_rather_than_reported_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], differ: ModuleType
) -> None:
    """A scan that found nothing has not told you that there is nothing.

    Without this, pointing the tool at a wrong `--path` reports every name as
    added and nothing as dropped - a confident, meaningless all-clear, which is
    the exact failure this repository has spent a day cataloguing.
    """
    repo = _repo_with_tests(tmp_path, before="VALUE = 1\n", after="def test_new() -> None: ...\n")

    exit_code = _run_in(repo, ["HEAD~1", "HEAD", "--path", "tests"], differ)

    assert exit_code == 2
    assert "would be vacuous" in capsys.readouterr().err


def test_an_unreadable_ref_is_reported_rather_than_treated_as_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], differ: ModuleType
) -> None:
    repo = _repo_with_tests(
        tmp_path, before="def test_a() -> None: ...\n", after="def test_a() -> None: ...\n"
    )

    exit_code = _run_in(repo, ["no-such-ref", "HEAD", "--path", "tests"], differ)

    assert exit_code == 2
    assert capsys.readouterr().err.strip()


# --- the real suite ----------------------------------------------------------


def test_it_reads_this_repository_and_finds_hundreds(differ: ModuleType) -> None:
    """Guards against the scan silently matching nothing in the real tree."""
    names = differ._test_names(
        (REAL_TESTS / "test_store_creating_readers.py").read_text(encoding="utf-8")
    )

    assert "test_every_engine_call_site_is_classified" in names, (
        "the census test that was deleted on 2026-08-23 is the canonical example "
        "and should be findable by this parser"
    )


# --- helpers -----------------------------------------------------------------


def _repo_with_tests(root: Path, *, before: str, after: str) -> Path:
    """A throwaway repo with two commits, so `HEAD~1` and `HEAD` both resolve."""
    (root / "tests").mkdir(parents=True)
    sample = root / "tests" / "test_sample.py"

    def run(*args: str) -> None:
        subprocess.run(args, cwd=root, check=True, capture_output=True)

    run("git", "init", "-q")
    run("git", "config", "user.email", "test@example.invalid")
    run("git", "config", "user.name", "test")

    sample.write_text(before, encoding="utf-8")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "before")

    sample.write_text(after, encoding="utf-8")
    run("git", "add", "-A")
    # `--allow-empty`: two of these fixtures deliberately commit identical
    # content, because what varies is the *working tree* afterwards. Without it
    # git refuses and the fixture fails for a reason unrelated to the test.
    run("git", "commit", "-q", "--allow-empty", "-m", "after")
    return root


def _run_in(repo: Path, argv: list[str], differ: ModuleType) -> int:
    """Run `main` with `repo` as REPO, in-process so capsys sees the output.

    The module is loaded from a path at runtime, so mypy cannot know it defines
    `REPO`. Binding it to `Any` once says that in one place, where `getattr`
    would say it twice and ruff would rewrite it back.
    """
    import os

    module: Any = differ
    original_repo = module.REPO
    previous = Path.cwd()
    module.REPO = repo
    os.chdir(repo)
    try:
        result: int = module.main(argv)
        return result
    finally:
        os.chdir(previous)
        module.REPO = original_repo
