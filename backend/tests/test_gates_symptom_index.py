"""The symptom index in ``docs/governance/gates.md`` must reach every entry.

The file's entries are titled as *conclusions* - "A denominator reconstructed
from the numerator flatters itself" - which reads well and is findable only by
someone who already knows the lesson. On 2026-09-06 two entries were
rediscovered from scratch mid-incident rather than found, one of them recording
the exact two hashes the reader was staring at. The index exists to key that
corpus by observable symptom instead.

An index nobody maintains is worse than none, because a stale one is trusted.
So this pins it. Following ``test_adr_index.py``: a completeness check that
passes on a complete file has demonstrated nothing, so every invariant here is
driven by a mutation that must make it fire - including the two vacuity
mutations, since an extractor that silently matches nothing passes every
containment assertion ever written against it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATES = REPO_ROOT / "docs" / "governance" / "gates.md"

_INDEX_HEADING = "## Symptom index"


def _read(path: Path) -> str:
    """Read without newline translation, then normalise explicitly.

    ``Path.read_text`` applies universal-newline translation, so CRLF becomes
    LF before any assertion sees it. That is harmless for substring matching
    and actively misleading for anything counting line endings, so the decode
    is done here rather than inherited.
    """
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _entry_titles(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^### (.+)$", text, re.M)]


def _index_block(text: str) -> str:
    start = text.find(_INDEX_HEADING)
    if start == -1:
        return ""
    end = text.find("\n---\n", start)
    return text[start:end] if end != -1 else text[start:]


def _unreachable(text: str) -> list[str]:
    block = _index_block(text)
    if not block:
        return _entry_titles(text)
    return [t for t in _entry_titles(text) if t not in block]


@pytest.fixture(scope="module")
def gates_text() -> str:
    return _read(GATES)


def test_the_extractor_finds_the_corpus_it_claims_to_check(gates_text: str) -> None:
    """Guard the denominator before asserting anything about the numerator.

    ``_unreachable`` returns ``[]`` when ``_entry_titles`` matches nothing, so
    the completeness assertion below is vacuously true against a regex that has
    quietly stopped matching. This is the "zero and false are values" entry in
    the file being tested, applied to the test itself.
    """
    titles = _entry_titles(gates_text)
    assert len(titles) >= 30, (
        f"expected the gates.md scar corpus, found {len(titles)} entries - "
        "the heading regex has probably stopped matching"
    )
    assert _INDEX_HEADING in gates_text, "the symptom index section is missing entirely"


def test_every_entry_is_reachable_from_the_symptom_index(gates_text: str) -> None:
    missing = _unreachable(gates_text)
    assert not missing, (
        "these gates.md entries have no symptom line, so they are findable only "
        "by someone who already knows the lesson:\n  - " + "\n  - ".join(missing)
    )


def test_the_index_sits_above_the_corpus_it_indexes(gates_text: str) -> None:
    """An index below the material it indexes is found only after it is not needed."""
    first_entry = gates_text.find("\n### ")
    assert gates_text.find(_INDEX_HEADING) < first_entry


# --------------------------------------------------------------------------
# Negative controls. Each mutation must make the check above fire.
# --------------------------------------------------------------------------

_COMPLETE = """# Readiness gates

## Symptom index

- You observe a thing - *An entry that exists*
- You observe another thing - *A second entry*

---

## What gates cannot catch

### An entry that exists

Body.

### A second entry

Body.
"""


def test_the_complete_control_passes() -> None:
    """Without this, a check that fails unconditionally would satisfy every
    mutation below and look rigorous doing it."""
    assert _unreachable(_COMPLETE) == []
    assert len(_entry_titles(_COMPLETE)) == 2


def test_an_entry_added_without_a_symptom_line_is_caught() -> None:
    mutated = _COMPLETE + "\n### A third entry nobody indexed\n\nBody.\n"
    assert _unreachable(mutated) == ["A third entry nobody indexed"]


def test_a_deleted_index_does_not_pass_vacuously() -> None:
    mutated = _COMPLETE.replace(_INDEX_HEADING, "## Something else")
    assert len(_unreachable(mutated)) == 2, (
        "removing the index must report every entry as unreachable, not zero"
    )


def test_an_emptied_index_does_not_pass_vacuously() -> None:
    mutated = re.sub(r"- You observe.*?\n- You observe.*?\n", "", _COMPLETE, flags=re.S)
    assert len(_unreachable(mutated)) == 2


def test_a_symptom_line_below_the_terminator_does_not_count() -> None:
    """The block ends at ``---``; text after it is corpus, not index.

    Without this the check would be satisfied by an entry's own title appearing
    in its own body, which is not a symptom line and helps nobody.
    """
    mutated = _COMPLETE.replace("- You observe another thing - *A second entry*\n", "")
    assert _unreachable(mutated) == ["A second entry"]
