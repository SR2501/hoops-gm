"""The editable install must point at the tree these tests live in.

`gates.md` records the incident as *"The import you got is not the tree you are
in"*: a single machine-global editable install is shared by every checkout, so
one `pip install -e` from any worktree silently redirects `import hoops_gm` for
all of them. Repointing it fixes the instance and not the class - the next
install from any worktree re-hijacks the lot.

**No CI job can ever catch this**, because CI installs into a clean environment
per job, from the checkout it is testing. The failure only exists on a machine
holding more than one checkout, which is to say a developer machine, which is to
say the only place where nothing was watching.

This guard reads the **install metadata** (`direct_url.json`) rather than the
resolved import, and that choice is load-bearing. Checking
`hoops_gm.__file__` would be masked by `PYTHONPATH`, which the local test
invocation sets: the import would resolve correctly through the path entry while
the hijacked editable install sat underneath it, undetected, waiting for the
first command run without `PYTHONPATH`. A guard that passes because of the way
you happened to invoke it is the can't-fail shape this repository keeps meeting.

What this cannot see: an installation that is not editable, a hijack by a
differently-named distribution, and any `.pth` file placed by something other
than pip. It checks one mechanism - the one that actually bit us.
"""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import pytest

DIST_NAME = "hoops-gm-backend"


def editable_source_dir(raw: str) -> Path | None:
    """Return the source directory of an editable install, or None.

    None means "this metadata does not describe an editable directory install",
    which covers a wheel install, a VCS install, and a non-editable local one.
    """
    info = json.loads(raw)
    if not info.get("dir_info", {}).get("editable", False):
        return None
    url = info.get("url", "")
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None
    return Path(url2pathname(parsed.path)).resolve()


def hijack_message(source: Path, expected: Path) -> str | None:
    """None when the install points here; an explanation when it does not.

    Extracted so the comparison itself is testable. Left inline, the real
    assertion's operands are only ever exercised against an environment where
    they agree, and `source == source` survives as a mutant - which it did,
    before this function existed.
    """
    if source == expected:
        return None
    return (
        f"The editable install of {DIST_NAME} points at {source}, but these "
        f"tests live in {expected}. Every `import hoops_gm` in this checkout is "
        f"resolving against a different tree unless PYTHONPATH happens to mask "
        f"it. Re-run `pip install -e .` from {expected}, or give this worktree "
        f"its own virtual environment - which is the structural fix, since "
        f"repointing only moves the hijack to whichever checkout ran it last."
    )


def test_editable_install_points_at_this_checkout() -> None:
    """The one that fires when a sibling worktree has hijacked the import."""
    try:
        dist = distribution(DIST_NAME)
    except PackageNotFoundError:
        pytest.skip(
            f"{DIST_NAME} is not installed in this interpreter, so no editable "
            "install exists to hijack anything. Not a pass - not applicable."
        )

    raw = dist.read_text("direct_url.json")
    if raw is None:
        pytest.skip(
            "no direct_url.json: this distribution was not installed from a "
            "local directory, so the editable-hijack class does not apply."
        )

    source = editable_source_dir(raw)
    if source is None:
        pytest.skip(
            "installed, but not as an editable directory install, so there is "
            "no shared pointer for another checkout to repoint."
        )

    expected = Path(__file__).resolve().parents[1]

    assert (problem := hijack_message(source, expected)) is None, problem


def test_non_editable_install_is_not_treated_as_editable() -> None:
    raw = json.dumps({"url": "file:///C:/somewhere/else", "dir_info": {}})
    assert editable_source_dir(raw) is None


def test_missing_dir_info_is_not_treated_as_editable() -> None:
    assert editable_source_dir(json.dumps({"url": "file:///C:/somewhere"})) is None


def test_vcs_install_is_not_treated_as_a_local_directory() -> None:
    raw = json.dumps({"url": "https://github.com/SR2501/hoops-gm", "dir_info": {"editable": True}})
    assert editable_source_dir(raw) is None


def test_editable_file_url_is_resolved_to_a_path() -> None:
    raw = json.dumps(
        {"url": "file:///C:/Users/example/checkout/backend", "dir_info": {"editable": True}}
    )
    resolved = editable_source_dir(raw)
    assert resolved is not None
    assert resolved.name == "backend"
    assert "checkout" in resolved.parts


def test_the_comparison_would_actually_fail_on_a_foreign_checkout() -> None:
    """The guard is only worth having if a hijack makes it fire."""
    here = Path(__file__).resolve().parents[1]
    foreign = editable_source_dir(
        json.dumps(
            {
                "url": "file:///C:/Users/steverones/hoops-gm-worktrees/other/backend",
                "dir_info": {"editable": True},
            }
        )
    )
    assert foreign is not None
    assert foreign != here

    problem = hijack_message(foreign, here)
    assert problem is not None
    assert str(foreign) in problem
    assert str(here) in problem


def test_matching_checkout_reports_no_problem() -> None:
    here = Path(__file__).resolve().parents[1]
    assert hijack_message(here, here) is None
