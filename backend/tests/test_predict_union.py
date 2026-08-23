"""The union predictor, and the two failure modes it must not paper over.

`scripts/predict_union.py` exists because two methods agreeing cannot exclude
the case where both are wrong in the same direction. Its value is therefore
entirely in being computed from *different facts* than the count it is checked
against — so the tests here pin the arithmetic and, more importantly, pin the
two cases where the arithmetic is silently inapplicable.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "predict_union.py"
REAL_HANDOFF = Path(__file__).resolve().parents[2] / "docs" / "handoff.md"


@pytest.fixture(scope="module")
def predictor() -> ModuleType:
    spec = importlib.util.spec_from_file_location("predict_union", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_arithmetic_is_base_plus_both_sides_additions(predictor: ModuleType) -> None:
    """The case it was built for: 241 + 1 + 1 = 243, driven on 2026-08-23."""
    assert predictor.predict(241, 242, 242) == 243
    assert predictor.predict(237, 238, 241) == 242


def test_a_side_that_added_nothing_contributes_nothing(predictor: ModuleType) -> None:
    assert predictor.predict(100, 100, 100) == 100
    assert predictor.predict(100, 105, 100) == 105


def test_the_pattern_matches_a_real_handoff_heading(predictor: ModuleType) -> None:
    """Anchored on the ISO date, so prose variation cannot hide an entry.

    The em-dash case is the one that actually bit: an entry written
    ``## 2026-08-23 — `frontend` — ...`` silently failed a grep anchored on a
    hyphen separator and was briefly reported as a lost entry.
    """
    hyphen = "## 2026-08-23 - quant - Land a ruling that existed only in a chat"
    em_dash = "## 2026-08-23 — `frontend` — the harness was a procedure"
    body = f"{hyphen}\n\nsome prose\n\n{em_dash}\n\nmore prose\n"

    assert len(predictor.DATED_ENTRY.findall(body)) == 2


def test_a_heading_that_is_not_a_dated_entry_is_not_counted(predictor: ModuleType) -> None:
    body = "## Not a date\n\n### 2026-08-23 - subsection, not an entry\n\n## 2026-08-23 - real\n"

    assert len(predictor.DATED_ENTRY.findall(body)) == 1


def test_it_counts_the_real_handoff_from_git(predictor: ModuleType) -> None:
    """Reads the blob out of `ref`, so all three sides work from one checkout.

    An earlier version asserted `from_git == from_disk`. That looked like a
    consistency check and was really an assertion that nobody had uncommitted
    handoff edits - so it went red the moment this lane appended its own entry
    before committing, which is the normal state of a lane mid-unit rather than
    a defect.

    The property actually worth pinning is the opposite one: reading a ref must
    be **independent** of the working tree, because that independence is what
    lets the predictor count `base`, `ours` and `theirs` from one checkout. So
    the disk count is used as a lower bound - `docs/handoff.md` is append-only,
    so the tree can hold more entries than `HEAD` but never fewer.
    """
    from_git = predictor.count_entries("HEAD")
    from_disk = len(predictor.DATED_ENTRY.findall(REAL_HANDOFF.read_text(encoding="utf-8")))

    assert from_git > 200, (
        "the real handoff holds hundreds of dated entries; a small count here means the "
        "pattern stopped matching, not that entries vanished"
    )
    assert from_disk >= from_git, (
        "the working tree holds fewer dated entries than HEAD, which append-only "
        "should make impossible - something removed an entry rather than adding one"
    )


def test_counting_a_ref_ignores_the_working_tree(
    predictor: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The independence the predictor rests on, asserted rather than assumed."""
    repo = _git_repo_with_handoff(tmp_path, "## 2026-08-23 - one\n")
    monkeypatch.chdir(repo)

    committed = predictor.count_entries("HEAD")
    (repo / "docs" / "handoff.md").write_text(
        "## 2026-08-23 - one\n\n## 2026-08-24 - two\n", encoding="utf-8"
    )

    assert committed == 1
    assert predictor.count_entries("HEAD") == 1, "counting a ref must not read the working tree"


def test_a_zero_base_is_refused_rather_than_predicted_from(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A pattern that matches nothing is not a file that contains nothing.

    This is the failure the whole surrounding effort is about: a search whose
    domain is wrong returns a confident, correct-looking zero. Predicting from
    it would produce a number that is arithmetically consistent and meaningless,
    so the script refuses instead.
    """
    repo = _git_repo_with_handoff(tmp_path, "# no dated entries here\n")

    exit_code = _run_in(repo, ["HEAD", "HEAD", "HEAD"])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "not the same as there being" in captured.err


def test_an_unreadable_ref_is_reported_rather_than_counted_as_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _git_repo_with_handoff(tmp_path, "## 2026-08-23 - an entry\n")

    exit_code = _run_in(repo, ["HEAD", "HEAD", "no-such-ref-anywhere"])

    assert exit_code == 2
    assert "could not read" in capsys.readouterr().err


# --- helpers ----------------------------------------------------------------


def _git_repo_with_handoff(root: Path, handoff: str) -> Path:
    """A throwaway repository with one commit, so `git show REF:path` works."""
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "handoff.md").write_text(handoff, encoding="utf-8")

    def run(*args: str) -> None:
        subprocess.run(args, cwd=root, check=True, capture_output=True)

    run("git", "init", "-q")
    run("git", "config", "user.email", "test@example.invalid")
    run("git", "config", "user.name", "test")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "handoff")
    return root


def _run_in(repo: Path, argv: list[str]) -> int:
    """Run the script's ``main`` with ``repo`` as the working directory.

    In-process rather than as a subprocess so ``capsys`` sees the output and a
    non-zero exit is a return value rather than something to parse.
    """
    spec = importlib.util.spec_from_file_location("predict_union_isolated", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    import os

    previous = Path.cwd()
    os.chdir(repo)
    try:
        result: int = module.main(argv)
        return result
    finally:
        os.chdir(previous)
