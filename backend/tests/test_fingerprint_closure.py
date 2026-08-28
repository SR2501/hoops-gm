"""Tests for ``scripts/fingerprint_closure.py``.

The script exists because ADR-019 publishes a load-bearing count - *34 files in
the closure, 3 fingerprinted* - that had no way to be recounted. A tool that
reports a number nobody checks is the same defect one level down, so these tests
drive the resolution rules against a synthetic package rather than asserting the
repository's current numbers, which will move.

Two of them assert **refusals**, because the failure this area keeps producing is
a confident zero over an empty domain: a closure walk that silently resolves
nothing, or a declared set read as empty, would both report a clean result and
mean nothing.
"""

from __future__ import annotations

import ast
import importlib.util
import io
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "fingerprint_closure.py"


def _load():
    spec = importlib.util.spec_from_file_location("fingerprint_closure", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fingerprint_closure = _load()


class TestTheClosureWalkResolvesWhatItClaims:
    def _package(self, tmp_path: Path, files: dict[str, str]) -> Path:
        root = tmp_path / "src"
        for relative, body in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        return root

    def test_transitive_imports_are_followed_not_just_direct_ones(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FAILS IF: the walk stops at depth one.

        The whole claim is about the *transitive* closure. A direct-only walk
        would have reported a far smaller gap and made the boundary look tighter
        than it is - the flattering direction, which is the one to test.
        """
        root = self._package(
            tmp_path,
            {
                "hoops_gm/__init__.py": "",
                "hoops_gm/gen.py": "from hoops_gm.middle import thing\n",
                "hoops_gm/middle.py": "from hoops_gm.deep import other\n",
                "hoops_gm/deep.py": "value = 1\n",
            },
        )
        monkeypatch.setattr(fingerprint_closure, "PACKAGE_ROOT", root)

        reached = fingerprint_closure.closure(root / "hoops_gm/gen.py")

        assert reached == {root / "hoops_gm/middle.py", root / "hoops_gm/deep.py"}

    def test_an_import_cycle_terminates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FAILS IF: the walk recurses forever on a cycle.

        `hoops_gm` has module cycles that only exist under `TYPE_CHECKING`, and
        the AST sees those imports whether or not they run.
        """
        root = self._package(
            tmp_path,
            {
                "hoops_gm/__init__.py": "",
                "hoops_gm/a.py": "from hoops_gm.b import x\n",
                "hoops_gm/b.py": "from hoops_gm.a import y\n",
            },
        )
        monkeypatch.setattr(fingerprint_closure, "PACKAGE_ROOT", root)

        reached = fingerprint_closure.closure(root / "hoops_gm/a.py")

        assert reached == {root / "hoops_gm/a.py", root / "hoops_gm/b.py"}

    def test_a_package_resolves_to_its_init_and_a_module_to_its_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FAILS IF: importing a subpackage silently resolves to nothing.

        `hoops_gm.ingest.nba` is imported as a package in the real generator, and
        a resolver that only tried `<name>.py` would drop it without complaining -
        shrinking the reported closure and the apparent gap with it.
        """
        root = self._package(
            tmp_path,
            {
                "hoops_gm/__init__.py": "",
                "hoops_gm/gen.py": "import hoops_gm.pkg\nfrom hoops_gm.leaf import z\n",
                "hoops_gm/pkg/__init__.py": "",
                "hoops_gm/leaf.py": "",
            },
        )
        monkeypatch.setattr(fingerprint_closure, "PACKAGE_ROOT", root)

        reached = fingerprint_closure.closure(root / "hoops_gm/gen.py")

        assert reached == {root / "hoops_gm/pkg/__init__.py", root / "hoops_gm/leaf.py"}

    def test_imports_outside_the_package_are_not_counted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FAILS IF: stdlib and third-party imports inflate the closure.

        The boundary is about repository files whose bytes we control. Counting
        `json` would make the gap look enormous and mean nothing.
        """
        root = self._package(
            tmp_path,
            {
                "hoops_gm/__init__.py": "",
                "hoops_gm/gen.py": "import json\nfrom sqlalchemy import select\n",
            },
        )
        monkeypatch.setattr(fingerprint_closure, "PACKAGE_ROOT", root)

        assert fingerprint_closure.closure(root / "hoops_gm/gen.py") == set()


class TestItRefusesRatherThanReportingAnEmptyDomain:
    def test_a_missing_declared_tuple_refuses(self, tmp_path: Path) -> None:
        """FAILS IF: a renamed constant yields an empty declared set.

        An empty declared set would make *every* closure file look
        unfingerprinted - a maximally alarming report produced by a rename. The
        script must refuse to report a count it cannot ground.
        """
        generator = tmp_path / "gen.py"
        generator.write_text("SOMETHING_ELSE = ('a.py',)\n", encoding="utf-8")

        with pytest.raises(fingerprint_closure.ClosureError) as caught:
            fingerprint_closure.declared_paths(generator)

        assert "DEFAULT_SOURCE_FINGERPRINT_PATHS" in str(caught.value)

    def test_an_absent_generator_refuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FAILS IF: a moved generator reports a closure of zero."""
        monkeypatch.setattr(fingerprint_closure, "GENERATOR", Path("nowhere/at/all.py"))

        with pytest.raises(fingerprint_closure.ClosureError):
            fingerprint_closure.report(io.StringIO())

    def test_an_annotated_declaration_is_read(self, tmp_path: Path) -> None:
        """FAILS IF: only bare assignment is handled.

        The real declaration is annotated - ``: Final[tuple[str, ...]] =`` - so a
        reader that only walked ``ast.Assign`` would refuse on the live file and
        the script would never run at all.
        """
        generator = tmp_path / "gen.py"
        generator.write_text(
            "from typing import Final\n"
            "DEFAULT_SOURCE_FINGERPRINT_PATHS: Final[tuple[str, ...]] = ('a.py', 'b.py')\n",
            encoding="utf-8",
        )

        assert fingerprint_closure.declared_paths(generator) == {"a.py", "b.py"}


class TestItRunsAgainstThisRepository:
    def test_the_report_runs_and_grounds_its_own_numbers(self) -> None:
        """FAILS IF: the script stops working against the real tree.

        Deliberately asserts *relationships*, not the counts ADR-019 quotes.
        Pinning 34 here would turn every honest change to the generator's imports
        into a failing test, and the tool exists to report that movement rather
        than to forbid it.
        """
        out = io.StringIO()

        assert fingerprint_closure.report(out) == 0

        text = out.getvalue()
        assert "transitive closure" in text
        assert "IN CLOSURE, NOT FINGERPRINTED" in text
        # The domain limit must reach the reader of the output, not only the
        # reader of the module docstring.
        assert "floor" in text

    def test_the_declared_set_is_not_empty_on_the_real_generator(self) -> None:
        """FAILS IF: the live parse silently yields nothing.

        A clean result over an empty domain is not a pass - the rule this
        repository has restated more than any other.
        """
        declared = fingerprint_closure.declared_paths(fingerprint_closure.GENERATOR)

        assert len(declared) >= 5
        assert all(path.startswith("backend/src/hoops_gm/") for path in declared)

    def test_the_generator_declares_itself(self) -> None:
        """FAILS IF: the manifest stops fingerprinting the code that wrote it.

        The generator's own bytes are the one input whose change can move every
        number at once, and it is reached by no import of itself - so nothing
        else in this script would notice its removal.
        """
        declared = fingerprint_closure.declared_paths(fingerprint_closure.GENERATOR)
        relative = fingerprint_closure.GENERATOR.relative_to(
            fingerprint_closure.REPO_ROOT
        ).as_posix()

        assert relative in declared


def test_the_script_parses_as_python() -> None:
    """FAILS IF: the file is committed broken.

    It is loaded by path rather than imported as a package module, so a syntax
    error would surface as a collection error somewhere confusing.
    """
    ast.parse(SCRIPT.read_text(encoding="utf-8"))
