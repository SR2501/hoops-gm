"""`docs/handoff.md` must end with a newline, or its own entry count lies.

**The regression is silent and it happened twice in one day.** `predict_union.py`
counts dated entries with `^## \\d{4}-\\d{2}-\\d{2}`, anchored at a line start.
Append to a file with no trailing newline and the heading is welded onto the
last line - the entry is present, uncounted, and completely unremarkable in a
diff. `open(path, "a").write("## ...")`, the natural way to append, produces
exactly that.

The first occurrence was healed incidentally by the next merge and filed as
"self-heals, no repair needed". True of the instance, false of the class: the
second arrived hours later on a different lane's merge. These tests are the
class.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "check_doc_terminators.py"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_doc_terminators", _SCRIPT)
    assert spec and spec.loader, f"cannot load {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_an_unterminated_file_is_reported(
    checker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actual defect, in the form it arrived in twice."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "handoff.md").write_bytes(b"...and I have SQLite only.")
    monkeypatch.setattr(checker, "REPO", tmp_path)

    problems = checker.unterminated(("docs/handoff.md",))

    assert len(problems) == 1
    assert "does not end with a newline" in problems[0]


def test_a_terminated_file_passes(
    checker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The negative control.

    A check that always fires and a check that never fires are equally useless,
    and one run cannot tell them apart.
    """
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "handoff.md").write_bytes(b"...and I have SQLite only.\n")
    monkeypatch.setattr(checker, "REPO", tmp_path)

    assert checker.unterminated(("docs/handoff.md",)) == []


def test_a_missing_file_fails_rather_than_skips(
    checker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scan that found nothing has not told you that there is nothing.

    If `docs/handoff.md` is absent the append-only machinery is meaningless, so
    the honest report is a failure. A green skip reads as a pass in a summary
    line, which is how a whole job spent its first day unable to run.
    """
    monkeypatch.setattr(checker, "REPO", tmp_path)

    problems = checker.unterminated(("docs/handoff.md",))

    assert len(problems) == 1
    assert "not found" in problems[0]


def test_an_empty_file_fails(
    checker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`b"".endswith(b"\\n")` is False, but the message should say *empty*.

    An empty file and an unterminated one need different repairs, and a check
    that reports the wrong one sends the reader to the wrong fix.
    """
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "handoff.md").write_bytes(b"")
    monkeypatch.setattr(checker, "REPO", tmp_path)

    problems = checker.unterminated(("docs/handoff.md",))

    assert len(problems) == 1
    assert "empty" in problems[0]


def test_the_welding_it_prevents_is_real(checker: ModuleType) -> None:
    """Drive the consequence, so the check's justification is not folklore.

    Positive control on the extractor first, because a zero from a pattern that
    matches nothing anywhere is not evidence about the unterminated case.
    """
    import re

    dated = re.compile(rb"(?m)^## \d{4}-\d{2}-\d{2}")
    entry = b"## 2026-08-27 - backend - a new entry\n"

    assert len(dated.findall(b"tail.\n" + b"\n" + entry)) == 1, "extractor is broken"
    assert len(dated.findall(b"tail.\n" + entry)) == 1, "terminated base: entry is visible"
    assert len(dated.findall(b"tail." + entry)) == 0, "unterminated base: entry is LOST"


def test_the_repository_s_own_files_are_terminated(checker: ModuleType) -> None:
    """The live check, against this repository rather than a fixture."""
    assert checker.unterminated() == []
