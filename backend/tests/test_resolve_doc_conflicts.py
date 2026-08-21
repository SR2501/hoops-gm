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

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "resolve_doc_conflicts.py"


def _load(tmp_root: pathlib.Path):
    """Import the script with REPO_ROOT pointed at a scratch tree.

    Imported rather than shelled out so a mutation can be applied to a live
    function object — the review's independence check worked that way and it is
    the only way to demonstrate that two guards fail *separately*.
    """
    spec = importlib.util.spec_from_file_location(f"rdc_{tmp_root.name}", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO_ROOT = tmp_root
    return module


HEADER = "**1 done - 0 blocked - 1 pending - 2 total**"


def _backlog(items: str, header: str = HEADER) -> str:
    return f"# Build backlog\n\n{header}\n\n{items}"


ITEM_A = "### `alpha` - Alpha\n\n- [x] **done**\n- **Depends on:** `nothing`\n"
ITEM_B = "### `beta` - Beta\n\n- [ ] **pending**\n- **Depends on:** `alpha`\n"


def test_separator_is_matched_by_equality_not_by_prefix(tmp_path):
    """Pins the defect that wrote a separator *into* a resolved file.

    `=======` is exactly seven. An RST table rule of 21 and a setext underline
    are content, and treating them as structure corrupted real documents.
    """
    module = _load(tmp_path)
    assert module.is_conflict_marker("=======")
    assert not module.is_conflict_marker("=" * 21)
    assert not module.is_conflict_marker("=" * 5)
    assert not module.is_conflict_marker("=" * 21 + " " + "=" * 59)


def test_real_git_markers_are_all_recognised(tmp_path):
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


def test_help_writes_nothing(tmp_path):
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


def test_two_surviving_headers_are_refused(tmp_path):
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


def test_note_only_conflict_is_refused_rather_than_given_a_second_header(tmp_path):
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


def test_intro_prose_sharing_a_hunk_with_the_header_is_refused(tmp_path):
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


def test_diff3_base_section_refuses_by_name(tmp_path):
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
    assert "diff3" in message
    assert "would drop" not in message, "blamed the slug guard for a diff3 file"


def test_body_conflict_is_refused_rather_than_collapsed(tmp_path):
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


def test_header_count_conflict_is_still_resolved(tmp_path):
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


def test_slug_guard_is_independent_of_the_anchor(tmp_path, monkeypatch):
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


def test_quoted_begin_marker_is_refused_not_consumed(tmp_path):
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


def test_unreadable_files_are_reported_not_silently_passed(tmp_path):
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
