"""The import you get must be the tree you are in, measured rather than declared.

`gates.md` records the incident: a machine-global editable install is a
singleton, so whichever checkout last ran `pip install -e` owns `import hoops_gm`
for every checkout on the machine. It caused three false diagnoses in one night,
one of which rewrote working `alembic` code before the claim was withdrawn.
**No CI job can see it** - CI installs into a clean environment from the checkout
it is testing - so the only place it can be caught is the developer machine,
which is the one place nothing was watching.

**This file's first version read `direct_url.json` and was wrong**, in a way the
house rules name exactly: *validation of form cannot catch errors of meaning*.
`direct_url.json` is pip's record of the last install's source directory. It is
well-formed, accurate about what pip was told, and **does not determine what
`import` returns**. The live machine disproved it within the hour: the metadata
said the install pointed at the main checkout while
`_editable_impl_hoops_gm_backend.pth` - the file that actually puts a directory
on `sys.path` - pointed at a *different worktree on an unmerged branch*. The old
guard passed, cheerfully, while every import in the main checkout was resolving
to that branch's bytes.

So this measures the effect. It resolves the package **in a subprocess with
`PYTHONPATH` stripped**, because both halves of that matter: a subprocess sees
what a fresh command would see rather than what this already-configured
interpreter has, and stripping `PYTHONPATH` removes the mask that makes the
hijack invisible to the tests that would otherwise catch it. Our own test
invocation pins `PYTHONPATH`, so a check performed in-process would pass through
the path entry while the mis-pointed install sat underneath, waiting for the
first command run without it.

The metadata is still read, but only to assert it **agrees** with the resolution.
Their disagreement is not a nuisance, it is the precise signature of the bug
found here: a stale `.pth` outliving a later reinstall.

What this cannot see: a non-editable installation, a hijack by a differently
named distribution, and any `sys.path` manipulation done inside application code
rather than by the installer.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import pytest

DIST_NAME = "hoops-gm-backend"

BACKEND_DIR = Path(__file__).resolve().parents[1]
EXPECTED_SRC = BACKEND_DIR / "src"


def recorded_source_dir(raw: str) -> Path | None:
    """The project directory pip recorded for an editable install, or None.

    None means "this metadata does not describe an editable directory install",
    which covers a wheel, a VCS install, and a non-editable local one. It is a
    record of intent and is **not** evidence about what `import` will return.
    """
    info = json.loads(raw)
    if not info.get("dir_info", {}).get("editable", False):
        return None
    parsed = urlparse(info.get("url", ""))
    if parsed.scheme != "file":
        return None
    return Path(url2pathname(parsed.path)).resolve()


def resolve_in_clean_process() -> Path | None:
    """Where a fresh command would import the package from, or None.

    `PYTHONPATH` is stripped deliberately. With it set - as our own test runs set
    it - the import resolves through the path entry and the mis-pointed install
    underneath stays invisible, which is the whole failure mode.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    probe = (
        "import hoops_gm, pathlib; print(pathlib.Path(hoops_gm.__file__).resolve().parent.parent)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    if proc.returncode != 0:
        return None
    return Path(proc.stdout.strip()).resolve()


def hijack_message(actual: Path, expected: Path) -> str | None:
    """None when the import lands in this tree; an explanation when it does not.

    Extracted so the comparison itself is testable. Left inline, its operands are
    only ever exercised where they agree, and `actual == actual` survives as a
    mutant - which it did, before this function existed.
    """
    if actual == expected:
        return None
    return (
        f"`import hoops_gm` resolves to {actual}, but these tests live in "
        f"{expected}. This checkout is running another tree's bytes, and every "
        f"failure it produces will look like a bug in your own change. Re-run "
        f"`python -m pip install -e . --no-deps` from {BACKEND_DIR}, then verify "
        f"by content rather than by path - a symbol that exists on exactly one "
        f"branch - because a corrected path can still serve stale bytes."
    )


def disagreement_message(recorded: Path, actual: Path) -> str | None:
    """None when pip's record and the real resolution agree.

    Extracted for the same reason as `hijack_message`: left inline, the operands
    are only exercised where they agree and an always-true mutant survives.
    """
    if recorded / "src" == actual:
        return None
    return (
        f"pip records the editable install as {recorded}, but `import hoops_gm` "
        f"actually resolves to {actual}. The metadata and the path entry "
        f"disagree, which means a stale .pth has outlived a later reinstall. "
        f"Trust the resolution, not the record: reinstall from {BACKEND_DIR}."
    )


def test_the_import_you_get_is_the_tree_you_are_in() -> None:
    """The authoritative check: measured resolution, not recorded intent."""
    actual = resolve_in_clean_process()
    if actual is None:
        pytest.skip(
            "hoops_gm is not importable without PYTHONPATH, so there is no "
            "editable install to be mis-pointed. Not applicable rather than passing."
        )
    assert (problem := hijack_message(actual, EXPECTED_SRC)) is None, problem


def test_recorded_metadata_agrees_with_actual_resolution() -> None:
    """A stale .pth outliving a reinstall is exactly how this bug hid."""
    try:
        dist = distribution(DIST_NAME)
    except PackageNotFoundError:
        pytest.skip(f"{DIST_NAME} is not installed in this interpreter.")

    raw = dist.read_text("direct_url.json")
    if raw is None:
        pytest.skip("no direct_url.json: not installed from a local directory.")

    recorded = recorded_source_dir(raw)
    if recorded is None:
        pytest.skip("installed, but not as an editable directory install.")

    actual = resolve_in_clean_process()
    if actual is None:
        pytest.skip("package not importable in a clean process.")

    assert (problem := disagreement_message(recorded, actual)) is None, problem


def test_non_editable_install_is_not_treated_as_editable() -> None:
    raw = json.dumps({"url": "file:///C:/somewhere/else", "dir_info": {}})
    assert recorded_source_dir(raw) is None


def test_missing_dir_info_is_not_treated_as_editable() -> None:
    assert recorded_source_dir(json.dumps({"url": "file:///C:/somewhere"})) is None


def test_vcs_install_is_not_treated_as_a_local_directory() -> None:
    raw = json.dumps({"url": "https://github.com/SR2501/hoops-gm", "dir_info": {"editable": True}})
    assert recorded_source_dir(raw) is None


def test_editable_file_url_is_resolved_to_a_path() -> None:
    raw = json.dumps(
        {"url": "file:///C:/Users/example/checkout/backend", "dir_info": {"editable": True}}
    )
    resolved = recorded_source_dir(raw)
    assert resolved is not None
    assert resolved.name == "backend"
    assert "checkout" in resolved.parts


def test_a_foreign_checkout_produces_a_message_naming_both_trees() -> None:
    """The guard is only worth having if a hijack makes it fire."""
    foreign = Path(r"C:\Users\steverones\copilot-worktrees\hoops-gm\other\backend\src")
    assert foreign != EXPECTED_SRC

    problem = hijack_message(foreign, EXPECTED_SRC)
    assert problem is not None
    assert str(foreign) in problem
    assert str(EXPECTED_SRC) in problem


def test_matching_checkout_reports_no_problem() -> None:
    assert hijack_message(EXPECTED_SRC, EXPECTED_SRC) is None


def test_disagreement_between_record_and_resolution_is_reported() -> None:
    """The stale-.pth signature: pip says one tree, sys.path serves another."""
    recorded = Path(r"C:\Users\steverones\hoops-gm\backend")
    stale = Path(r"C:\Users\steverones\copilot-worktrees\hoops-gm\other\backend\src")

    assert disagreement_message(recorded, recorded / "src") is None

    problem = disagreement_message(recorded, stale)
    assert problem is not None
    assert str(recorded) in problem
    assert str(stale) in problem


def test_clean_process_resolution_ignores_pythonpath(tmp_path: Path) -> None:
    """The mask this guard exists to defeat, asserted with a decoy that could win.

    An earlier version pointed PYTHONPATH at a directory supplying no package, so
    honouring or stripping it gave the same answer and the test could not tell
    them apart - it passed while a mutant removed the stripping entirely. This
    plants a real importable `hoops_gm` on the path, so if the ambient
    PYTHONPATH were ever honoured the resolution would move to the decoy.
    """
    decoy = tmp_path / "hoops_gm"
    decoy.mkdir()
    (decoy / "__init__.py").write_text("", encoding="utf-8")

    before = resolve_in_clean_process()
    if before is None:
        pytest.skip("package not importable in a clean process.")
    assert before != tmp_path

    original = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = str(tmp_path)
    try:
        after = resolve_in_clean_process()
    finally:
        if original is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = original

    assert after == before, (
        f"the decoy at {tmp_path} captured the import, so this guard is reading "
        f"whatever PYTHONPATH happens to say rather than what the install does."
    )
