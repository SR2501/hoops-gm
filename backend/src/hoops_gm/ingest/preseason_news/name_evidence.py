"""Comparable name evidence for RotoWire news without resolving identity."""

from __future__ import annotations

from hoops_gm.identity import NormalizedName, normalize_name


def name_evidence_agrees(left: str, right: str) -> bool:
    """Compare names while preserving three-valued suffix evidence.

    RotoWire player URLs omit punctuation, so ``P.J.`` becomes ``pj`` in a
    slug. The shared normalizer correctly separates periods for ordinary names;
    this source-specific comparison closes only consecutive single-letter tokens
    so the title and URL remain comparable. A suffix present on only one side is
    unknown evidence because RotoWire omits real suffixes; two different stated
    suffixes are a contradiction.
    """
    left_name = normalize_name(left)
    right_name = normalize_name(right)
    if _base_key(left_name) != _base_key(right_name):
        return False
    return not (left_name.suffix and right_name.suffix and left_name.suffix != right_name.suffix)


def _base_key(normalized: NormalizedName) -> str:
    collapsed: list[str] = []
    initials: list[str] = []
    for token in normalized.key.split():
        if len(token) == 1:
            initials.append(token)
            continue
        if initials:
            collapsed.append("".join(initials))
            initials.clear()
        collapsed.append(token)
    if initials:
        collapsed.append("".join(initials))
    return " ".join(collapsed)
