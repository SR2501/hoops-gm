"""Regression tests for ``scripts/slugcheck.py``.

The tool exists because a recount cannot see a dropped backlog item. These
tests apply the same rule to the tool itself: each reproduces a clean-looking
comparison that the first implementation approved without having established
what its success sentence claimed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "slugcheck.py"
OPERATIONAL_ERROR = 2


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _backlog(*entries: tuple[str, str]) -> str:
    return "# Build backlog\n\n" + "".join(
        f"### `{slug}` - {title}\n\n- [ ] **pending**\n\nBody.\n\n" for slug, title in entries
    )


def _write(repo: Path, *entries: tuple[str, str]) -> None:
    path = repo / "docs" / "backlog.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_backlog(*entries), encoding="utf-8")


def _commit(repo: Path, message: str, *, allow_empty: bool = False) -> str:
    _git(repo, "add", "docs/backlog.md")
    args = ["commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    _git(repo, *args)
    return _git(repo, "rev-parse", "HEAD")


def _repo(
    tmp_path: Path,
    *,
    base: tuple[tuple[str, str], ...],
    mine: tuple[tuple[str, str], ...],
    theirs: tuple[tuple[str, str], ...],
    merged: tuple[tuple[str, str], ...],
) -> tuple[Path, str, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "slugcheck@example.test")
    _git(repo, "config", "user.name", "slugcheck tests")
    (repo / "scripts").mkdir()
    shutil.copy2(SCRIPT, repo / "scripts" / "slugcheck.py")

    _write(repo, *base)
    base_ref = _commit(repo, "base")

    _git(repo, "switch", "-c", "mine")
    _write(repo, *mine)
    mine_ref = _commit(repo, "mine", allow_empty=mine == base)

    _git(repo, "switch", "-c", "theirs", base_ref)
    _write(repo, *theirs)
    theirs_ref = _commit(repo, "theirs", allow_empty=theirs == base)

    _write(repo, *merged)
    return repo, base_ref, mine_ref, theirs_ref


def _run(
    repo: Path,
    base: str,
    mine: str,
    theirs: str,
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "slugcheck.py"), base, mine, theirs],
        cwd=cwd or repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_a_unilateral_deletion_cannot_be_subtracted_from_expected(tmp_path: Path) -> None:
    """Base {a}, mine {b}, theirs {a,b}, merged {b} must not pass.

    The first implementation subtracted anything either side dropped. That
    made one lane's deletion erase an item the other lane still preserved,
    approving exactly the loss this tool exists to catch.
    """
    repo, base, mine, theirs = _repo(
        tmp_path,
        base=(("a", "A"), ("kept", "Kept")),
        mine=(("kept", "Kept"),),
        theirs=(("a", "A"), ("kept", "Kept")),
        merged=(("kept", "Kept"),),
    )

    result = _run(repo, base, mine, theirs)

    assert result.returncode == 1
    assert "a" in result.stdout
    assert "missing from the merged file" in result.stdout


def test_a_claimed_merge_base_must_equal_git_merge_base(tmp_path: Path) -> None:
    repo, base, mine, theirs = _repo(
        tmp_path,
        base=(("base", "Base"),),
        mine=(("base", "Base"), ("mine", "Mine")),
        theirs=(("base", "Base"), ("theirs", "Theirs")),
        merged=(("base", "Base"), ("mine", "Mine"), ("theirs", "Theirs")),
    )

    result = _run(repo, theirs, mine, theirs)

    assert result.returncode == OPERATIONAL_ERROR
    assert base in result.stderr
    assert "not the merge base" in result.stderr


@pytest.mark.parametrize(
    ("mine", "theirs", "merged", "message"),
    [
        (
            (("base", "Base"), ("collision", "Mine"), ("collision", "Mine duplicate")),
            (("base", "Base"),),
            (("base", "Base"), ("collision", "Mine")),
            "duplicate",
        ),
        (
            (("base", "Base"), ("collision", "Mine")),
            (("base", "Base"), ("collision", "Theirs")),
            (("base", "Base"), ("collision", "Mine")),
            "independently added",
        ),
    ],
)
def test_duplicate_and_independently_added_colliding_slugs_are_operational_errors(
    tmp_path: Path,
    mine: tuple[tuple[str, str], ...],
    theirs: tuple[tuple[str, str], ...],
    merged: tuple[tuple[str, str], ...],
    message: str,
) -> None:
    repo, base, mine_ref, theirs_ref = _repo(
        tmp_path,
        base=(("base", "Base"),),
        mine=mine,
        theirs=theirs,
        merged=merged,
    )

    result = _run(repo, base, mine_ref, theirs_ref)

    assert result.returncode == OPERATIONAL_ERROR
    assert message in result.stderr
    assert "collision" in result.stderr


def test_an_empty_parse_is_an_operational_error_not_an_empty_union(tmp_path: Path) -> None:
    repo, base, mine, theirs = _repo(
        tmp_path,
        base=(),
        mine=(),
        theirs=(),
        merged=(),
    )

    result = _run(repo, base, mine, theirs)

    assert result.returncode == OPERATIONAL_ERROR
    assert "parsed zero backlog items" in result.stderr


def test_cli_resolves_the_worktree_from_the_script_not_the_callers_cwd(tmp_path: Path) -> None:
    repo, base, mine, theirs = _repo(
        tmp_path,
        base=(("base", "Base"),),
        mine=(("base", "Base"), ("mine", "Mine")),
        theirs=(("base", "Base"), ("theirs", "Theirs")),
        merged=(("base", "Base"), ("mine", "Mine"), ("theirs", "Theirs")),
    )
    caller = repo / "backend"
    caller.mkdir()

    result = _run(repo, base, mine, theirs, cwd=caller)

    assert result.returncode == 0, result.stderr
    assert "exactly the union" in result.stdout
