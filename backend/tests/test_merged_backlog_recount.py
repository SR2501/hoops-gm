"""Tests for ``scripts/merged_backlog_recount.py``.

The script exists for one case, so the tests are built around proving that case
is real, is missed by a per-branch check, and is caught after.

**The case, concretely.** Two lanes each file exactly one backlog item. Each
increments the headline count by one, so **both write the identical header
string**. Git does not conflict on a line both sides changed to the same text,
and the additions land in different regions of the file, so the merge is
completely clean. The merged file then has two more items than the merged
header claims -- and each branch, read on its own, is correct.

``test_the_existing_checker_passes_on_both_branches`` is the one that makes the
rest non-vacuous. It asserts that ``backlog_graph.py`` -- the tool we already
have -- reports **no defect** on either branch. Without it, this whole file
could be testing a gap that nothing had.

**What these tests do not establish.** They say nothing about whether CI catches
this. CI's ``pull_request`` run is checked out at a merge commit, so it plausibly
does, for the merge against ``main`` *as of that run*. The gap the script is
actually for is narrower and lives outside pytest's reach: ``main`` moving
between the last CI run and the merge button, and having no way to ask before
pushing. See the script's own docstring, which states that distinction and says
how to re-verify it against a live PR rather than asking anyone to believe it.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SCRIPT = SCRIPTS / "merged_backlog_recount.py"

BASE_HEADER = "**1 done - 0 blocked - 1 pending - 2 total**"
#: What each lane writes after adding one item. Identical on both branches,
#: which is exactly why git merges it without complaint.
LANE_HEADER = "**1 done - 0 blocked - 2 pending - 3 total**"
#: What the merged file actually contains.
TRUE_MERGED_HEADER = "**1 done - 0 blocked - 3 pending - 4 total**"


def _filler(tag: str) -> str:
    """Unique prose attached to each entry, so hunks do not share diff context.

    Not decoration, and the tag must travel **with** its item. Two earlier
    shapes both failed: entries packed three lines apart put the header and the
    first item in one hunk, and filler numbered by *position* renumbered every
    later block when an item was inserted above it, rewriting the whole file.
    Either way every edit conflicts, which would quietly turn this file into a
    test of the conflict path and never exercise the clean merge it exists for.
    """
    return "".join(
        f"Filler line {index} for {tag}, kept distinct on purpose.\n" for index in range(8)
    )


def _entry(slug: str, title: str, marker: str) -> str:
    return f"### `{slug}` - {title}\n\n- {marker}\n\n" + _filler(slug)


ALPHA = _entry("alpha", "An item that is finished", "[x] **done**")
BETA = _entry("beta", "An item that is not", "[ ] **pending**")
GAMMA = _entry("gamma", "The item lane A filed", "[ ] **pending**")
DELTA = _entry("delta", "The item lane B filed", "[ ] **pending**")


def _backlog(header: str, items: list[str]) -> str:
    return "# Build backlog\n\n" + header + "\n\n" + _filler("head") + "\n" + "\n".join(items)


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("merged_backlog_recount", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def graph(script: ModuleType) -> ModuleType:
    loaded = script.load_backlog_graph(
        (SCRIPTS / "backlog_graph.py").read_bytes(),
        source_label=str(SCRIPTS / "backlog_graph.py"),
    )
    assert isinstance(loaded, ModuleType)
    return loaded


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    done = subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    assert done.returncode == 0, (
        f"git {' '.join(args)} failed: {done.stderr.decode('utf-8', 'replace')}"
    )
    return done


def _write(repo: Path, text: str) -> None:
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "backlog.md").write_bytes(text.encode("utf-8"))
    parser = repo / "scripts" / "backlog_graph.py"
    if not parser.exists():
        parser.parent.mkdir(exist_ok=True)
        parser.write_bytes((SCRIPTS / "backlog_graph.py").read_bytes())


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


@pytest.fixture
def two_lanes(tmp_path: Path) -> Path:
    """A repo where two lanes each filed one item and both wrote the same header.

    Lane A inserts its item **above** the existing entries and lane B appends
    below, so the two additions never touch the same region. The only line both
    sides edit is the header, and they edit it to byte-identical text, which git
    merges silently.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")

    _write(repo, _backlog(BASE_HEADER, [ALPHA, BETA]))
    _commit(repo, "base")

    _git(repo, "branch", "lane-b")

    _write(repo, _backlog(LANE_HEADER, [GAMMA, ALPHA, BETA]))
    _commit(repo, "lane A files one item")

    _git(repo, "checkout", "lane-b")
    _write(repo, _backlog(LANE_HEADER, [ALPHA, BETA, DELTA]))
    _commit(repo, "lane B files one item")

    _git(repo, "checkout", "main")
    return repo


def _merged_text(script: ModuleType, repo: Path) -> str:
    text = script.merged_backlog_text("main", "lane-b", cwd=repo)
    assert isinstance(text, str)
    return text


class TestTheGapIsReal:
    def test_the_merge_is_clean(self, script: ModuleType, two_lanes: Path) -> None:
        """No conflict. Nobody is prompted to look at anything."""
        text = _merged_text(script, two_lanes)
        assert "<<<<<<<" not in text
        assert "gamma" in text and "delta" in text

    def test_the_existing_checker_passes_on_both_branches(
        self, graph: ModuleType, two_lanes: Path
    ) -> None:
        """The load-bearing test: today's tool is green on both sides.

        If this ever fails, ``backlog_graph.py`` already covers the case and
        this entire script is redundant and should be deleted.
        """
        for ref in ("main", "lane-b"):
            blob = subprocess.run(
                ["git", "cat-file", "blob", f"{ref}:docs/backlog.md"],
                cwd=two_lanes,
                capture_output=True,
                check=True,
            ).stdout.decode("utf-8")
            _, defects = graph.parse_backlog(blob)
            assert [d.kind for d in defects] == [], (
                f"backlog_graph already objects to {ref}; the premise of this "
                "script is that each branch is individually clean"
            )

    def test_the_merged_header_is_nonetheless_wrong(
        self, script: ModuleType, graph: ModuleType, two_lanes: Path
    ) -> None:
        """Four items, and a header both branches agreed said three."""
        text = _merged_text(script, two_lanes)
        assert LANE_HEADER in text
        assert TRUE_MERGED_HEADER not in text

        items, defects = graph.parse_backlog(text)
        assert len(items) == 4
        assert [d.kind for d in defects] == ["header-disagrees-with-items"]


class TestTheScriptCatchesIt:
    def test_it_fails_on_the_clean_merge_with_the_wrong_header(
        self, script: ModuleType, two_lanes: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = script.main(["--base", "main", "--head", "lane-b", "--repo", str(two_lanes)])
        assert code == 1
        out = capsys.readouterr().out
        assert "header-disagrees-with-items" in out
        assert "4 items" in out

    def test_it_passes_once_the_header_is_recounted(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        """Non-vacuity: a clean merge whose header is right must go green.

        Without this the failing test above would be satisfied by a script that
        returns 1 unconditionally.

        This needs its own repo rather than the two-lane one, and the reason is
        itself the point: to reach a *clean* merge only one side may touch the
        header. Correcting lane B's header while ``main`` still carries the
        wrong one makes the two sides edit line 3 differently, which conflicts
        -- so that arrangement would exercise the exit-2 path and prove nothing
        about exit 0.
        """
        repo = tmp_path / "onelane"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _write(repo, _backlog(BASE_HEADER, [ALPHA, BETA]))
        _commit(repo, "base")

        _git(repo, "checkout", "-b", "lane")
        _write(repo, _backlog(LANE_HEADER, [ALPHA, BETA, DELTA]))
        _commit(repo, "one lane files one item and recounts")
        _git(repo, "checkout", "main")

        assert script.main(["--base", "main", "--head", "lane", "--repo", str(repo)]) == 0

    def test_reconciling_the_two_headers_would_not_have_helped(
        self, script: ModuleType, two_lanes: Path
    ) -> None:
        """Both branches claim 3; the answer is 4. Neither side is the answer.

        This is why the rule is "recount from the merged file" rather than
        "resolve the conflict sensibly" -- there is no arithmetic on the two
        headers that reaches the truth, because each was computed before the
        other lane's item existed.
        """
        text = _merged_text(script, two_lanes)
        assert text.count(LANE_HEADER) == 1
        assert TRUE_MERGED_HEADER not in text


class TestAnUnevaluatedRunIsNotAPass:
    def test_a_real_conflict_reports_two_not_zero(
        self, script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A check that could not run must never report success."""
        repo = tmp_path / "conflict"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _write(repo, _backlog(BASE_HEADER, [ALPHA, BETA]))
        _commit(repo, "base")

        _git(repo, "branch", "other")
        _write(repo, _backlog("**2 done - 0 blocked - 0 pending - 2 total**", [ALPHA, BETA]))
        _commit(repo, "main edits the header")

        _git(repo, "checkout", "other")
        _write(repo, _backlog("**0 done - 0 blocked - 2 pending - 2 total**", [ALPHA, BETA]))
        _commit(repo, "other edits the header differently")
        _git(repo, "checkout", "main")

        code = script.main(["--base", "main", "--head", "other", "--repo", str(repo)])
        assert code == 2
        assert "COULD NOT EVALUATE" in capsys.readouterr().out

    def test_a_missing_backlog_reports_two(
        self, script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = tmp_path / "nobacklog"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        (repo / "README.md").write_text("nothing here\n", encoding="utf-8")
        _commit(repo, "base")
        _git(repo, "branch", "other")

        code = script.main(["--base", "main", "--head", "other", "--repo", str(repo)])
        assert code == 2
        assert "COULD NOT EVALUATE" in capsys.readouterr().out


class TestAParsedEmptySetIsNotAPass:
    def test_a_header_claiming_items_with_no_headings_fails(
        self, script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Regression: exact-head implementation printed 0 items, OK, exit 0."""
        repo = tmp_path / "empty"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _write(
            repo,
            "# Build backlog\n\n"
            "**64 done - 0 blocked - 124 pending - 188 total**\n\n"
            "This file claims items and contains no item headings.\n",
        )
        _commit(repo, "base")
        _git(repo, "branch", "other")

        code = script.main(["--base", "main", "--head", "other", "--repo", str(repo)])

        assert code == 1
        out = capsys.readouterr().out
        assert "0 items" in out
        assert "FAIL [no-items]" in out
        assert "OK:" not in out


class TestTheMergedParserJudgesTheMergedBacklog:
    def test_a_parser_change_in_the_merge_cannot_be_bypassed_by_the_checkout(
        self, script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The old implementation loaded the parser beside ``__file__``.

        The target branch changes the parser so the ordinary header becomes
        invalid. The checkout parser running this test still accepts that
        header. Passing here therefore proves the parser came from the merged
        target tree rather than from the checkout.
        """
        repo = tmp_path / "parser-change"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _write(repo, _backlog(BASE_HEADER, [ALPHA, BETA]))
        _commit(repo, "base")
        _git(repo, "checkout", "-b", "other")

        parser_path = repo / "scripts" / "backlog_graph.py"
        source = parser_path.read_text(encoding="utf-8")
        old = (
            r'HEADER_RE = re.compile(r"^\*\*(\d+) done - (\d+) blocked - '
            r'(\d+) pending - (\d+) total\*\*$")'
        )
        new = 'HEADER_RE = re.compile(r"^THIS MERGE REQUIRES A DIFFERENT HEADER$")'
        assert old in source, "the mutation must alter the parser rule it claims to test"
        parser_path.write_text(source.replace(old, new), encoding="utf-8")
        _commit(repo, "change the merged parser semantics")
        _git(repo, "checkout", "main")

        # The checkout parser accepts the backlog. This proves the failure below
        # cannot have come from the parser running the test suite.
        checkout_graph = script.load_backlog_graph(
            (SCRIPTS / "backlog_graph.py").read_bytes(),
            source_label=str(SCRIPTS / "backlog_graph.py"),
        )
        _, checkout_defects = checkout_graph.parse_backlog(_backlog(BASE_HEADER, [ALPHA, BETA]))
        assert checkout_defects == []

        code = script.main(["--base", "main", "--head", "other", "--repo", str(repo)])

        assert code == 1
        assert "FAIL [missing-header]" in capsys.readouterr().out


class TestEveryMergedParserDefectIsFatal:
    def test_a_partially_parsed_backlog_cannot_report_ok(
        self, script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A malformed item used to be a note while the wrapper exited 0.

        The header deliberately matches the one item the parser *can* read, so
        the header comparison alone is green. The second malformed heading is
        a real item the parser lost, which means the header is not trustworthy
        even though its arithmetic matches the parseable subset.
        """
        repo = tmp_path / "partial"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        malformed = "### An item with no machine-readable slug\n\n- [ ] **pending**\n"
        _write(
            repo,
            _backlog("**1 done - 0 blocked - 0 pending - 1 total**", [ALPHA]) + "\n" + malformed,
        )
        _commit(repo, "base")
        _git(repo, "branch", "other")

        code = script.main(["--base", "main", "--head", "other", "--repo", str(repo)])

        assert code == 1
        out = capsys.readouterr().out
        assert "FAIL [malformed-heading]" in out
        assert "OK:" not in out


class TestMergedParserFailuresAreUnevaluated:
    def test_a_syntax_error_in_the_merged_parser_returns_two(
        self, script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A parser that cannot load is unevaluated, not a header defect."""
        repo = tmp_path / "broken-parser"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _write(repo, _backlog(BASE_HEADER, [ALPHA, BETA]))
        _commit(repo, "base")
        _git(repo, "checkout", "-b", "other")
        (repo / "scripts" / "backlog_graph.py").write_text(
            "def this_will_not_parse(:\n",
            encoding="utf-8",
        )
        _commit(repo, "break the merged parser")
        _git(repo, "checkout", "main")

        code = script.main(["--base", "main", "--head", "other", "--repo", str(repo)])

        assert code == 2
        out = capsys.readouterr().out
        assert "COULD NOT EVALUATE" in out
        assert "SyntaxError" in out
        assert "OK:" not in out


class TestItReadsBytes:
    def test_a_non_ascii_backlog_survives_the_round_trip(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        """The instrument must not re-encode its own sample.

        An earlier draft decoded git's output as the console codepage and died
        on a non-ASCII byte 195 KB into the real backlog. Same class as counting
        a file's CRLF endings through a pipeline that inserts them.
        """
        repo = tmp_path / "unicode"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        item = "### `jokic` - An item naming Nikola Joki\u0107\n\n- [ ] **pending**\n"
        _write(repo, _backlog("**0 done - 0 blocked - 1 pending - 1 total**", [item]))
        _commit(repo, "base")
        _git(repo, "branch", "other")

        text = script.merged_backlog_text("main", "other", cwd=repo)
        assert "Joki\u0107" in text
        assert script.main(["--base", "main", "--head", "other", "--repo", str(repo)]) == 0
