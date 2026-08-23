"""Console-bound text must survive the console it is printed to.

**The gate that was missing.** CI runs on Linux with a UTF-8 console, so every
check in this repository is green about an environment chosen for
reproducibility and silent about the one the owner actually works in. On
Windows, Python writes to a cp1252 console, and a character outside that
encoding arrives as a replacement mark. `pytest` mangled six assertion messages
that way on 2026-08-23, and `scripts/resolve_doc_conflicts.py` mangled the line
telling a blocked lane what to type next.

That is the worst possible placement. Guidance text is read when someone is
stuck, mid-rebase, on an unfamiliar branch, deciding whether to follow the
advice or route around the check — and the advice was arriving broken.

**Docstrings and comments are deliberately exempt.** They are read in an editor,
which handles UTF-8 fine, and typography there costs nothing. The constraint is
only on strings a console prints.

**Checked on the string's *value*, not on the source bytes.** That distinction
is not theoretical: `resolve_doc_conflicts.py` wrote its em dash as the escape
``\\u2014``, so the file was pure ASCII on disk and the rendered output was
still broken. A grep for the character would have reported the file clean.
"""

from __future__ import annotations

import ast
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Where this rule applies today, and therefore what it does *not* cover.
#:
#: ``scripts/`` are operator tools whose whole output is guidance.
#: ``backend/tests/`` is assertion text, read when something has already failed.
#:
#: **``backend/src/`` is measured and deliberately excluded**: it holds 5 such
#: strings across 3 CLI modules, and 2 of those 3 are pinned by whole-file
#: SHA-256 in the committed cohort manifest
#: (``docs/adapters/nba-injury-report-cohort-2025-12-08--2026-01-04.json``), so
#: editing them invalidates its provenance and fails
#: ``test_cohort_evidence.py``. Fixing the one unblocked module and leaving its
#: two siblings would be arbitrary. The right moment is whenever that manifest
#: is next regenerated; this note is here so the number is known rather than
#: rediscovered.
CHECKED_ROOTS = ("scripts", "backend/tests")

#: Substitutes for the characters that actually turn up in prose here. Not
#: exhaustive, and not meant to be — the test reports whatever it finds, and
#: choosing a replacement is a judgement about the sentence.
SUGGESTED = {
    "\u2014": "-",
    "\u2013": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u00a7": "Section ",
    "\u00a0": " ",
}


def _describe(ch: str) -> str:
    """Name a character without printing it.

    ``repr(ch)`` would embed the offending character in the very message that
    warns about it, so the report would arrive garbled on the console it is
    describing. Found by triggering this check from a Windows shell and reading
    what came out — which is the same method the check exists to encourage.
    """
    return f"U+{ord(ch):04X} {unicodedata.name(ch, 'unnamed')}"


def _console_strings(tree: ast.AST) -> list[tuple[int, str]]:
    """String constants that reach a console: assert messages, print, sys.exit.

    These three cover every way this repository currently addresses a human at
    a terminal. A logger call is not included: structured logs are rendered by
    a handler that owns its own encoding, and JSON output escapes non-ASCII.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        holders: list[ast.AST] = []
        if isinstance(node, ast.Assert) and node.msg is not None:
            holders.append(node.msg)
        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None)
            if isinstance(func, ast.Attribute):
                name = func.attr
            module = getattr(getattr(func, "value", None), "id", None)
            if name == "print" or (name == "exit" and module == "sys"):
                holders.extend(node.args)
        for holder in holders:
            for sub in ast.walk(holder):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    found.append((sub.lineno, sub.value))
    return found


def _offenders() -> list[str]:
    reports: list[str] = []
    for root in CHECKED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
                continue
            for lineno, value in _console_strings(tree):
                bad = sorted({ch for ch in value if ord(ch) > 127})
                if bad:
                    named = ", ".join(_describe(ch) for ch in bad)
                    reports.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}: {named}")
    return reports


def test_the_scan_covers_files_at_all() -> None:
    """A clean result over an empty domain is not a pass.

    The failure this whole area keeps producing is a check whose domain is
    narrower than its hazard, reporting a confident zero. So count what was
    scanned before believing what was found.
    """
    scanned = [p for root in CHECKED_ROOTS for p in (REPO_ROOT / root).rglob("*.py")]

    assert len(scanned) > 20, (
        f"only {len(scanned)} files scanned across {CHECKED_ROOTS}; the roots are "
        f"wrong or the checkout is partial, and a clean result would mean nothing"
    )


def test_console_text_is_printable_on_a_windows_console() -> None:
    offenders = _offenders()

    assert offenders == [], (
        "These strings are printed to a console and contain characters a Windows "
        "cp1252 console cannot render, so they reach their reader garbled:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse ASCII in anything a terminal prints. Common substitutions: "
        + ", ".join(f"{_describe(bad)} -> {good!r}" for bad, good in sorted(SUGGESTED.items()))
        + ".\nDocstrings and comments are exempt and need no change: they are read "
        "in an editor, which handles UTF-8.\nNote that writing the character as an "
        "escape does not help - the check reads the string's value, because "
        "'\\u2014' in the source is pure ASCII on disk and still broken on screen."
    )


def test_the_report_itself_survives_the_console_it_describes() -> None:
    """The report must not embed the character it is warning about.

    A first version interpolated ``repr(ch)``, so a message explaining that an
    em dash cannot be printed arrived with a mangled em dash in it. That is the
    same defect one level up, and it is the fifth time in this unit that a
    check's domain turned out narrower than its hazard: the offending character
    entered at *runtime*, through an f-string, where a scan for non-ASCII
    *literals* could never see it.

    So this asserts the rendered output rather than the source, which is the
    only formulation that could have caught it.
    """
    rendered = "\n".join(_describe(ch) for ch in SUGGESTED)
    rendered += "".join(_describe(ch) for ch in ("\u2014", "\u00a7", "\u2026"))

    assert rendered.isascii(), "the encoding report is not itself printable"
    assert "EM DASH" in _describe("\u2014")
    assert "U+2014" in _describe("\u2014")


def test_the_check_reads_values_rather_than_source_bytes() -> None:
    """Pins the property that made the real defect findable.

    ``scripts/resolve_doc_conflicts.py`` carried its em dash as ``\\u2014``. The
    file was ASCII; the output was not. Any check operating on the file's bytes
    would have called it clean.
    """
    escaped = ast.parse('assert x, "an escaped \\u2014 dash"')
    literal = ast.parse('assert x, "a literal \u2014 dash"')

    for tree in (escaped, literal):
        values = [value for _, value in _console_strings(tree)]
        assert any(ord(ch) > 127 for value in values for ch in value)
