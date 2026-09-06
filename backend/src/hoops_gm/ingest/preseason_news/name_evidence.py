"""Comparable name evidence for RotoWire news without resolving identity."""

from __future__ import annotations

from hoops_gm.identity import normalize_name


def name_evidence_key(raw: str) -> str:
    """Normalize spelling while retaining suffix evidence.

    RotoWire player URLs omit punctuation, so ``P.J.`` becomes ``pj`` in a
    slug. The shared normalizer correctly separates periods for ordinary names;
    this source-specific evidence key closes only consecutive single-letter
    tokens so the title and URL remain comparable.
    """
    normalized = normalize_name(raw)
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
    return f"{' '.join(collapsed)} {normalized.suffix}".strip()
