"""Executable coverage for `scripts/resolve_doc_conflicts.py`.

This file exists because a review asked whether a mutation to the resolver's
guards is caught by any test, and the answer was **no test invokes this script
at all** — `git grep -l resolve_doc_conflicts` returned one path, the script
itself, and CI runs nothing from `scripts/` except the secret scan.

That mattered more than an ordinary coverage gap. Every one of this script's
known defects was **silent data loss at exit 0**, all three were found in
production rather than by a check, and five parallel agent sessions depend on
it. `docs/governance/gates.md` says a skipped check is a failure rather than a
neutral result; a check that was never written is the same thing with less
warning.

Each test below pins a defect that actually occurred, named in its docstring,
so that a future edit which reintroduces one fails here rather than in
someone's rebase.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import subprocess
import sys
import types
from typing import Any

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "resolve_doc_conflicts.py"


def _load(tmp_root: pathlib.Path) -> types.ModuleType:
    """Import the script with REPO_ROOT pointed at a scratch tree.

    Imported rather than shelled out so a mutation can be applied to a live
    function object — the review's independence check worked that way and it is
    the only way to demonstrate that two guards fail *separately*.
    """
    spec = importlib.util.spec_from_file_location(f"rdc_{tmp_root.name}", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Typed `Any` for the assignment because mypy --strict cannot know a
    # dynamically loaded module's attributes, while ruff rewrites `setattr`
    # with a constant name back to attribute form. The `hasattr` assert is what
    # keeps this honest: a typo would otherwise create a *new* attribute and
    # leave every test silently pointed at the real repository — which is the
    # exact defect review found in the round-3 `--help` test.
    assert hasattr(module, "REPO_ROOT"), "script no longer defines REPO_ROOT"
    loaded: Any = module
    loaded.REPO_ROOT = tmp_root
    return module


HEADER = "**1 done - 0 blocked - 1 pending - 2 total**"


def _backlog(items: str, header: str = HEADER) -> str:
    return f"# Build backlog\n\n{header}\n\n{items}"


ITEM_A = "### `alpha` - Alpha\n\n- [x] **done**\n- **Depends on:** `nothing`\n"
ITEM_B = "### `beta` - Beta\n\n- [ ] **pending**\n- **Depends on:** `alpha`\n"


def test_separator_is_matched_by_equality_not_by_prefix(tmp_path: pathlib.Path) -> None:
    """Pins the defect that wrote a separator *into* a resolved file.

    `=======` is exactly seven. An RST table rule of 21 and a setext underline
    are content, and treating them as structure corrupted real documents.
    """
    module = _load(tmp_path)
    assert module.is_conflict_marker("=======")
    assert not module.is_conflict_marker("=" * 21)
    assert not module.is_conflict_marker("=" * 5)
    assert not module.is_conflict_marker("=" * 21 + " " + "=" * 59)


def test_real_git_markers_are_all_recognised(tmp_path: pathlib.Path) -> None:
    """The matcher must accept what git actually emits, not what we assume.

    Includes the `|||||||` base marker, which only appears under `diff3` and
    `zdiff3` and is therefore the one a developer on the default style never
    sees.
    """
    module = _load(tmp_path)
    for line in (
        "<<<<<<< HEAD",
        "||||||| 1234567",
        "=======",
        ">>>>>>> other-branch",
    ):
        assert module.is_conflict_marker(line), line


def test_help_writes_nothing(tmp_path: pathlib.Path) -> None:
    """Pins the defect where `--help` performed a full resolution.

    Run **in-process against a patched `REPO_ROOT`**, not as a subprocess with
    `cwd=tmp_path`. Review found the subprocess form inert: `REPO_ROOT` is
    derived from the *script's* location, not the working directory, so the
    child operated on the real repository regardless. The test asserted a
    scratch file was unchanged — a file the subprocess would never touch — and
    it passed while a mutation rewrote this repository's own backlog. A test
    that cannot fail is worse than no test, and one that mutates the tree under
    test is worse again.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    backlog.write_text(_backlog(ITEM_A + "\n" + ITEM_B), encoding="utf-8")
    handoff = docs / "handoff.md"
    handoff.write_text("## 2026-08-21\n\nentry\n", encoding="utf-8")
    before = (backlog.read_bytes(), handoff.read_bytes())

    module = _load(tmp_path)
    assert module.main(["--help"]) == 0
    assert (backlog.read_bytes(), handoff.read_bytes()) == before

    assert module.main(["--dry-run"]) == 2
    assert (backlog.read_bytes(), handoff.read_bytes()) == before


def test_two_surviving_headers_are_refused(tmp_path: pathlib.Path) -> None:
    """Covers the `written == 2` path, which no test reached.

    A stash-style label (`<<<<<<< Updated upstream`) means the collapse regex —
    which is anchored on `HEAD` — never matches, so both sides' headers
    survive. This assertion is the only thing that catches it.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    original = (
        "# Build backlog\n\n"
        "<<<<<<< Updated upstream\n**1 done - 0 blocked - 1 pending - 2 total**\n"
        "=======\n**0 done - 0 blocked - 2 pending - 2 total**\n"
        ">>>>>>> Stashed changes\n\n" + ITEM_A + "\n" + ITEM_B
    )
    backlog.write_text(original, encoding="utf-8")
    module = _load(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_backlog(backlog)

    assert "found 2" in str(excinfo.value)
    assert backlog.read_text(encoding="utf-8") == original


def test_note_only_conflict_is_refused_rather_than_given_a_second_header(
    tmp_path: pathlib.Path,
) -> None:
    """The recount note is accumulated incident history — merge it by hand.

    Pins the F2b regression: when the collapsed block held the note but *not*
    the header, the note-carries-the-header replacement injected a second one
    and the `written != 1` assertion then refused with a message claiming
    "both sides' headers survived" — which was false, because this function had
    created the second one line earlier. Now the block simply does not qualify
    for collapse, so no header is injected and the refusal says the true thing.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    original = (
        "# Build backlog\n\n" + HEADER + "\n\n"
        "<<<<<<< HEAD\n(Recomputed from the status markers in this finished file, ours.)\n"
        "=======\n(Recomputed from the status markers in this finished file, theirs.)\n"
        ">>>>>>> other\n\n" + ITEM_A + "\n" + ITEM_B
    )
    backlog.write_text(original, encoding="utf-8")
    module = _load(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_backlog(backlog)

    message = str(excinfo.value)
    assert "more than the header count line" in message
    assert "found 2" not in message, "refused for the wrong reason"
    assert backlog.read_text(encoding="utf-8") == original


def test_intro_prose_sharing_a_hunk_with_the_header_is_refused(tmp_path: pathlib.Path) -> None:
    """The real file's layout: intro sentence line 3, count line 5.

    One ordinary hunk covers both. The previous predicate — "block contains a
    count line" — collapsed it and deleted the sentence, both sides, exit 0.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    original = (
        "# Build backlog\n\n"
        "<<<<<<< HEAD\nGenerated from the planning session on 2026-08-17.\n\n"
        + HEADER
        + "\n=======\nGenerated from the planning session, revised.\n\n"
        "**0 done - 0 blocked - 2 pending - 2 total**\n>>>>>>> other\n\n" + ITEM_A + "\n" + ITEM_B
    )
    backlog.write_text(original, encoding="utf-8")
    module = _load(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_backlog(backlog)

    assert "more than the header count line" in str(excinfo.value)
    assert backlog.read_text(encoding="utf-8") == original
    assert "Generated from the planning session" in backlog.read_text(encoding="utf-8")


def test_diff3_base_section_refuses_by_name(tmp_path: pathlib.Path) -> None:
    """A heading only in the base means both sides deleted it — not a loss.

    Refusing is right; the previous message blamed the slug guard and sent the
    operator to diff a slug set against main for an item legitimately gone.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    backlog.write_text(
        _backlog(
            ITEM_A
            + "\n<<<<<<< HEAD\n"
            + ITEM_B
            + "||||||| base\n### `gamma` - Gamma\n\n- [ ] **pending**\n"
            + "=======\n"
            + ITEM_B
            + ">>>>>>> other\n"
        ),
        encoding="utf-8",
    )
    module = _load(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_backlog(backlog)

    message = str(excinfo.value)
    assert "resolves the two-sided form only" in message
    assert "would drop" not in message, "blamed the slug guard for a diff3 file"


def test_blank_only_conflict_is_refused_without_injecting_a_header(tmp_path: pathlib.Path) -> None:
    """Pins the fourth iteration: the predicate was vacuously true on nothing.

    Two lanes deleting the same paragraph and leaving a different number of
    trailing blank lines produces a conflict whose entire content is blank —
    ordinary `git merge` output, not a constructed case. The old predicate
    skipped the markers, skipped the blanks and returned True having never
    seen a count line, so a header was injected where one already existed and
    the script refused claiming both sides' headers had survived.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    original = (
        "# Build backlog\n\n"
        + HEADER
        + "\n\n<<<<<<< HEAD\n\n=======\n>>>>>>> other\n\n"
        + ITEM_A
        + "\n"
        + ITEM_B
    )
    backlog.write_text(original, encoding="utf-8")
    module = _load(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_backlog(backlog)

    message = str(excinfo.value)
    assert "no content at all" in message
    assert "found 2" not in message, "injected a header, then blamed the merge"
    assert backlog.read_text(encoding="utf-8") == original


def test_a_line_merely_containing_the_count_shape_is_not_a_count_line(
    tmp_path: pathlib.Path,
) -> None:
    """Defends `fullmatch` over `search`, which is the whole v3-to-v4 fix.

    Reverting that one word restores "block *contains* a count line", the
    predicate that deleted this file's own intro sentence. Nothing else in the
    suite fails when it is reverted.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    original = (
        "# Build backlog\n\n"
        "<<<<<<< HEAD\n- recount: " + HEADER + "\n"
        "=======\n- recount: **0 done - 0 blocked - 2 pending - 2 total**\n"
        ">>>>>>> other\n\n" + HEADER + "\n\n" + ITEM_A + "\n" + ITEM_B
    )
    backlog.write_text(original, encoding="utf-8")
    module = _load(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_backlog(backlog)

    assert "more than the header count line" in str(excinfo.value)
    assert backlog.read_text(encoding="utf-8") == original


def test_a_quoted_marker_line_is_content_not_structure(tmp_path: pathlib.Path) -> None:
    """Pins the fifth iteration: markers classified by prefix, not position.

    A line of *content* beginning `<<<<<<< ` was read as structure, skipped by
    the predicate, and the block judged to hold nothing but count lines — then
    deleted at exit 0 under "Safe to stage".

    The same reasoning was already written one function over in the same
    commit: `resolve_append_only` refuses a begin marker inside an open block
    because it is content, not structure. The argument existed, correct, in
    this file, and did not reach here.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    original = (
        "# Build backlog\n\n"
        "<<<<<<< HEAD\n" + HEADER + "\n"
        "<<<<<<< Updated upstream\n"
        "=======\n" + HEADER + "\n"
        ">>>>>>> other\n\n" + ITEM_A + "\n" + ITEM_B
    )
    backlog.write_text(original, encoding="utf-8")
    module = _load(tmp_path)

    with pytest.raises(SystemExit):
        module.resolve_backlog(backlog)

    after = backlog.read_text(encoding="utf-8")
    assert "<<<<<<< Updated upstream" in after, "quoted marker was deleted"
    assert after == original


def test_the_one_to_one_check_refuses_a_missing_status_marker(tmp_path: pathlib.Path) -> None:
    """The last guard in the file that nothing pinned.

    Pre-existing rather than new here, but it is the one that catches a
    resolution preserving every slug while dropping a status marker — which is
    precisely the loss the slug guard is blind to.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    backlog.write_text(
        _backlog(ITEM_A + "\n### `beta` - Beta\n\n- **Depends on:** `alpha`\n"),
        encoding="utf-8",
    )
    module = _load(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_backlog(backlog)

    assert "not 1:1" in str(excinfo.value)


def test_a_second_separator_is_content_not_structure(tmp_path: pathlib.Path) -> None:
    """The classifier's own separator rule, which nothing covered.

    `_block_content_lines` carries a private copy of the separator test — the
    first `=======` is structure, a second is content. Review found that rule
    correct in the code and unreached by any test: dropping `not
    seen_separator` left the whole suite green while a literal `=======` in
    the block was deleted at exit 0.

    It matters more than an ordinary gap because a seven-wide row of `=` is a
    Markdown setext underline and an RST table rule, which is **defect #1 of
    this change**. The fix for that was applied to `is_conflict_marker` and
    never travelled to the classifier's own copy — the same shape as the fifth
    iteration, a correct rule that did not reach the second place it was needed.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    original = (
        "# Build backlog\n\n"
        "<<<<<<< HEAD\n" + HEADER + "\n"
        "=======\n" + HEADER + "\n"
        "=======\n"
        ">>>>>>> other\n\n" + ITEM_A + "\n" + ITEM_B
    )
    backlog.write_text(original, encoding="utf-8")
    module = _load(tmp_path)

    with pytest.raises(SystemExit):
        module.resolve_backlog(backlog)

    after = backlog.read_text(encoding="utf-8")
    assert after == original, "a second separator was consumed as structure"
    assert after.count("=======") == 2


def test_the_real_cli_reads_sys_argv(tmp_path: pathlib.Path) -> None:
    """Pins the *wiring*, which every in-process test leaves untouched.

    Review reverted `args = sys.argv[1:] if argv is None else argv` to
    `args = []` and all twelve tests passed, while `--help` on the real CLI
    rewrote this repository's backlog — the original defect restored in full
    with a green suite. The in-process tests cover the parse; only a
    subprocess covers the wiring.

    The script is copied into the scratch tree so `REPO_ROOT`, which derives
    from the script's own location, resolves inside it and the real repository
    is unreachable **by construction** rather than by the child's cwd.
    """
    (tmp_path / "scripts").mkdir()
    copy = tmp_path / "scripts" / "resolve_doc_conflicts.py"
    copy.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    backlog.write_text(_backlog(ITEM_A + "\n" + ITEM_B), encoding="utf-8")
    handoff = docs / "handoff.md"
    handoff.write_text("## 2026-08-21\n\nentry\n", encoding="utf-8")
    before = (backlog.read_bytes(), handoff.read_bytes())

    result = subprocess.run(
        [sys.executable, str(copy), "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert (backlog.read_bytes(), handoff.read_bytes()) == before


def test_body_conflict_is_refused_rather_than_collapsed(tmp_path: pathlib.Path) -> None:
    """The High finding: a conflict in an item's *body* was silently deleted.

    The block carries no `### ` heading and no status marker, so the slug guard
    saw no change and the 1:1 heading/marker check balanced — the script exited
    0 and printed "Safe to stage" having deleted both sides' `**Depends on:**`
    edges. That is worse than losing an item outright: `AGENTS.md` defines a
    task as ready when every dependency is done, so a deleted edge makes a
    **blocked item look ready**.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    conflicted = _backlog(
        ITEM_A
        + "\n### `beta` - Beta\n\n- [ ] **pending**\n"
        + "<<<<<<< HEAD\n- **Depends on:** `alpha`\n=======\n"
        + "- **Depends on:** `alpha`, `gamma`\n>>>>>>> other\n"
    )
    backlog.write_text(conflicted, encoding="utf-8")
    module = _load(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_backlog(backlog)

    assert "more than the header count line" in str(excinfo.value)
    assert backlog.read_text(encoding="utf-8") == conflicted, "file was rewritten"


def test_header_count_conflict_is_still_resolved(tmp_path: pathlib.Path) -> None:
    """The anchor must not break the one case the script exists for.

    A refusal that fires on everything is not a fix, it is the cry-wolf guard
    the next person loosens.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    backlog.write_text(
        "# Build backlog\n\n"
        "<<<<<<< HEAD\n**1 done - 0 blocked - 1 pending - 2 total**\n=======\n"
        "**0 done - 0 blocked - 2 pending - 2 total**\n>>>>>>> other\n\n" + ITEM_A + "\n" + ITEM_B,
        encoding="utf-8",
    )
    module = _load(tmp_path)
    module.resolve_backlog(backlog)

    text = backlog.read_text(encoding="utf-8")
    assert "<<<<<<<" not in text
    assert "**1 done - 0 blocked - 1 pending - 2 total**" in text
    assert text.count("done - ") == 1, "two header blocks survived"
    assert "`alpha`" in text and "`beta`" in text


def test_slug_guard_is_independent_of_the_anchor(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two layers must fail *separately*, which is the argument for both.

    Verified by mutation rather than by reading: the collapse predicate is
    replaced with one that accepts everything — the exact pre-fix behaviour —
    and the slug guard must still refuse and must name what would be lost.

    Scoped with `monkeypatch` rather than by assigning `module.re.sub`, which
    patched the *stdlib* `re` module process-wide for the duration.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    conflicted = _backlog(
        ITEM_A
        + "\n<<<<<<< HEAD\n"
        + ITEM_B
        + "=======\n### `gamma` - Gamma\n\n- [ ] **pending**\n>>>>>>> other\n"
    )
    backlog.write_text(conflicted, encoding="utf-8")
    module = _load(tmp_path)
    monkeypatch.setattr(module, "_is_only_count_lines", lambda _block: True)

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_backlog(backlog)

    message = str(excinfo.value)
    assert "would drop" in message
    assert "beta" in message
    assert backlog.read_text(encoding="utf-8") == conflicted, "file was rewritten"


def test_quoted_begin_marker_is_refused_not_consumed(tmp_path: pathlib.Path) -> None:
    """An append-only doc quoting a marker at line start was silently eaten.

    `docs/handoff.md` quotes conflict markers today. Inline backticks survive
    only because they do not start the line; a fenced block would not.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    handoff = docs / "handoff.md"
    original = (
        "## 2026-08-21\n\n"
        "<<<<<<< HEAD\n"
        "The resolver saw a line reading\n"
        "<<<<<<< HEAD\n"
        "and consumed it.\n"
        "=======\n"
        "theirs\n"
        ">>>>>>> other\n"
    )
    handoff.write_text(original, encoding="utf-8")
    module = _load(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_append_only(handoff)

    assert "inside an open block" in str(excinfo.value)
    assert handoff.read_text(encoding="utf-8") == original


def test_unreadable_files_are_reported_not_silently_passed(tmp_path: pathlib.Path) -> None:
    """A verdict must not cover files the scan could not read.

    A latin-1 `.md` holding a complete conflict block scanned clean and the
    script printed "no conflict marker in any text file".
    """
    (tmp_path / "docs").mkdir()
    bad = tmp_path / "docs" / "legacy.md"
    bad.write_bytes("caf\xe9\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> x\n".encode("latin-1"))
    module = _load(tmp_path)

    found, unread = module.surviving_markers()
    assert any("legacy.md" in entry for entry in unread), unread
    assert found == [], "a latin-1 file should not be claimed as scanned"


def test_writes_preserve_lf_and_do_not_flip_the_file_to_crlf(tmp_path: pathlib.Path) -> None:
    """A tool the lanes are told to run rewrote the whole append-only log.

    `path.write_text(..., encoding="utf-8")` uses Python's text mode, which
    translates every `\n` to `\r\n` on Windows. Running this script therefore
    rewrote all 28,596 lines of `docs/handoff.md`.

    **`core.autocrlf=true` does not save you, which is the part that made this
    survive unnoticed.** Measured on 2026-08-27 in a repository with autocrlf
    enabled: the staged blob kept its CRLF while `origin/main` was LF, and
    `git diff --numstat` reported the entire log as changed. That reads exactly
    like the catastrophic append-only breach the byte-prefix check exists to
    detect - produced by the tool run to verify the append.

    Asserted on the **bytes** of the written file. Reading it back as text
    would normalise the newlines away and pass either way, which is the same
    "validation of form cannot catch errors of meaning" shape recorded in
    AGENTS.md.
    """
    module = _load(tmp_path)
    resolver: Any = module

    (tmp_path / "docs").mkdir()
    backlog = tmp_path / "docs" / "backlog.md"
    body = _backlog("### `a` - A\n\n- [x] **done**\n\n### `b` - B\n\n- [ ] **pending**\n")
    backlog.write_bytes(body.encode("utf-8"))
    assert backlog.read_bytes().count(b"\r\n") == 0, "fixture must start as LF"

    resolver.resolve_backlog(backlog)

    written = backlog.read_bytes()
    assert written.count(b"\r\n") == 0, (
        "the header recompute flipped the file to CRLF; on Windows this rewrites "
        "every line of an append-only document and destroys the byte-prefix check"
    )
    assert written.count(b"\n") > 0, "the file should still have line endings at all"

def test_the_recount_note_states_the_property_and_restates_no_count(
    tmp_path: pathlib.Path,
) -> None:
    """The note this tool writes must carry no integers.

    It used to interpolate ``{len(headings)} `###` headings and {len(markers)}
    markers``, which is a **second copy of the count**, in prose, in the one file
    whose entire header discipline is that a second copy is stale on arrival.
    ``backlog_graph.py`` checks only the header *line*, so the prose copy was
    precisely the unguarded duplicate that file warns about.

    The `demo-one-command` lane deleted exactly this restatement from
    `docs/backlog.md` on 2026-08-23 and recorded why. **It fixed the artefact and
    not the generator**, so this function put the numbers straight back on the
    next conflict — observed on 2026-08-27, four days later, on a branch that had
    never touched that prose. Fixing an instance and leaving the thing that
    emits it is how a corrected file un-corrects itself.

    The assertion is on **digits in the note**, not on the specific old wording.
    A test pinning the old sentence would pass for any rephrasing that
    reintroduced the numbers, which is the likelier regression: somebody adding
    "(N items)" for helpfulness. AGENTS.md: *"Do not restate that count here or
    anywhere else."*
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    backlog = docs / "backlog.md"
    backlog.write_text(
        _backlog(
            ITEM_A + "\n" + ITEM_B,
            header="<<<<<<< HEAD\n**9 done - 9 blocked - 9 pending - 27 total**\n"
            "=======\n**4 done - 0 blocked - 0 pending - 4 total**\n>>>>>>> other",
        ),
        encoding="utf-8",
    )

    module = _load(tmp_path)
    module.resolve_backlog(backlog)
    written = backlog.read_text(encoding="utf-8")

    # Recomputed from the file, agreeing with neither conflicting side.
    assert "**1 done - 0 blocked - 1 pending - 2 total**" in written
    assert "27 total" not in written
    assert "4 total" not in written

    start = written.index("(Recomputed from the status markers")
    note = written[start : written.index(")", start) + 1]
    assert "1:1" in note, "the property is still stated"
    # `1:1` is the *ratio* the note asserts, not a count of anything, so it is
    # removed before the digit scan rather than carved out of the pattern - a
    # pattern excusing digits around a colon would also excuse `169:169`.
    assert not re.search(r"\d", note.replace("1:1", "")), (
        f"the note restates a count: {note!r}"
    )
