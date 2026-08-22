"""Unit 2: the pre-unblind disclosure surface is a closed set that may not grow.

`data-engineer` owes this test under the frozen pre-registration
(`docs/models/injury-status-conversion-preregistration.md`, §2). The protocol's
invariant, quoted:

    The pre-unblind disclosure surface carries **no outcome-valued count beyond
    the single whole-cohort `participation_outcome_counts` the manifest already
    contains**, which is inherited adapter evidence and not a gate input. **No
    new outcome-keyed field may be added, at any granularity, in any manifest
    version.**

## Why this is a closed set rather than a granularity rule

A granularity rule was tried first — "outcome counts stay whole-cohort, only
denominators get the finer breakdown" — and both reviewers showed it was
necessary but not sufficient, and that it mis-sorted its own first two
applications. Three ways it failed:

* it constrains coarseness, not informativeness: the two existing whole-cohort
  marginals already yield the exact global play rate `292/1918 = 0.15224`;
* it is stated per-manifest, and git makes cross-manifest differencing free —
  the planned operation is *widening the same window*, so cohort B ⊃ cohort A
  with both committed, and `M_B[outcome] - M_A[outcome]` is the added dates'
  outcome marginal;
* "whole-cohort" is a label, not a size guarantee.

A rule reached by enumerating attacks is stale the next time a field is added.
A closed set needs nobody to reason about differencing, and it is enforceable
in CI, which the granularity rule was not.

## Why this scans a directory rather than a filename

`quant` review, and the reason is this lane's own doing. The protocol says "in
any manifest version", which reads as a constraint on the cohort manifest. But
Unit 1 committed `nba-injury-report-archive-reach-probe.json` to the same
directory — an evidence artifact that is **not** a manifest and would sit
outside a filename-scoped test entirely. The next evidence artifact would too.
So the scope is every JSON published under `docs/adapters/`, and a new file
there is covered on the day it lands rather than on the day someone remembers
to add it.

## What makes this test independent of what it checks

The allow-list is a literal in this file. It is deliberately **not** derived
from the manifest, because an expected value computed from the artefact under
test is a tautology wearing a measurement's costume — the failure this lane
shipped in Unit 1, where a vocabulary test read counts from a JSON this lane
had written and passed with every fixture deleted from the tree.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hoops_gm.db.models.enums import ParticipationOutcome

pytestmark = pytest.mark.adapter_contract

ADAPTER_DOCS = Path(__file__).resolve().parents[2] / "docs" / "adapters"

#: The outcome vocabulary, taken from the enum rather than restated. A new
#: member added there is covered here on the same commit, which a hardcoded
#: list would not be.
OUTCOME_VALUES = frozenset(outcome.value for outcome in ParticipationOutcome)

#: The frozen allow-list. Dotted paths, relative to each document's root.
#: **This set may shrink. It may never grow without a v3 of the protocol.**
ALLOWED_OUTCOME_KEYED_PATHS = frozenset(
    {
        f"participation_join.participation_outcome_counts.{value}"
        for value in ("played", "did_not_play", "did_not_dress", "not_with_team", "inactive")
    }
)


def _leaf_paths(node: Any, prefix: str = "") -> list[str]:
    """Every scalar leaf's dotted path, descending through lists as well as dicts.

    **Lists must be descended into, and an earlier version of this did not.**
    It returned a list as a leaf, which made everything inside one invisible to
    the scanner. The probe evidence artifact stores its per-report records in an
    `observations` list, so an outcome breakdown added to any record there was
    undetectable — caught by this file's own mutation M3, which stayed green
    against exactly the attack the directory scan exists to stop.

    A list contributes no path segment of its own. Indices would make the
    allow-list positional, so that adding a record could move a permitted path,
    and the invariant is about *field names* rather than about where a record
    happens to sit.
    """
    if isinstance(node, dict):
        paths: list[str] = []
        for key, value in node.items():
            paths.extend(_leaf_paths(value, f"{prefix}.{key}" if prefix else str(key)))
        return paths
    if isinstance(node, list):
        paths = []
        for item in node:
            paths.extend(_leaf_paths(item, prefix))
        return paths
    return [prefix]


def _outcome_keyed_paths(document: Any) -> set[str]:
    """Paths with a participation-outcome token as any segment."""
    return {path for path in _leaf_paths(document) if OUTCOME_VALUES & set(path.split("."))}


def _published_documents() -> list[Path]:
    return sorted(ADAPTER_DOCS.glob("*.json"))


def test_the_adapter_docs_directory_actually_has_documents_to_scan() -> None:
    """A scan over an empty directory passes vacuously and proves nothing.

    Every other test here iterates `_published_documents()`. If the glob ever
    stops matching — a moved directory, a renamed extension — those tests go
    green while checking nothing, which is the failure mode this project has
    now hit six times in one day.
    """
    documents = _published_documents()
    assert ADAPTER_DOCS.is_dir(), ADAPTER_DOCS
    assert len(documents) >= 3, [p.name for p in documents]


def test_the_outcome_vocabulary_is_not_empty() -> None:
    """The detector is only as good as the token set it matches on.

    An empty `OUTCOME_VALUES` would make `_outcome_keyed_paths` return the empty
    set for every document, so the allow-list check would pass no matter what
    was published. That is the same shape as a mutation harness scoring a
    collection error as a catch.
    """
    assert len(OUTCOME_VALUES) >= 5, sorted(OUTCOME_VALUES)
    assert "played" in OUTCOME_VALUES


def test_the_scanner_descends_into_lists() -> None:
    """The detector must see inside list-valued fields, and once it did not.

    Mutation M3 added an outcome breakdown to a record inside the probe
    artifact's `observations` list and the whole file stayed green, because
    `_leaf_paths` returned lists as leaves. A scanner that silently declines to
    look somewhere is worse than no scanner, because it reports clean.
    """
    document = {"records": [{"nested": {"played": 1}}, {"harmless": 2}]}
    assert _outcome_keyed_paths(document) == {"records.nested.played"}


def test_the_scanner_finds_an_outcome_at_any_depth() -> None:
    """Granularity is not the rule; the field name is, wherever it appears."""
    assert _outcome_keyed_paths({"a": {"b": {"c": {"inactive": 5}}}}) == {"a.b.c.inactive"}
    assert _outcome_keyed_paths({"played": 1}) == {"played"}
    assert _outcome_keyed_paths({"totals": [{"by_date": [{"did_not_dress": 2}]}]}) == {
        "totals.by_date.did_not_dress"
    }


def test_no_published_adapter_document_adds_an_outcome_keyed_field() -> None:
    """The invariant itself, across the whole published directory."""
    found: dict[str, set[str]] = {}
    for path in _published_documents():
        document = json.loads(path.read_text(encoding="utf-8"))
        paths = _outcome_keyed_paths(document)
        if paths:
            found[path.name] = paths

    all_paths = set().union(*found.values()) if found else set()
    added = all_paths - ALLOWED_OUTCOME_KEYED_PATHS

    assert not added, (
        "these outcome-keyed fields are not on the frozen allow-list, so the "
        "pre-unblind disclosure surface has grown:\n  "
        + "\n  ".join(sorted(added))
        + "\n\nThe frozen protocol permits no new outcome-keyed field at any "
        "granularity in any published version. Adding one needs a v3, not a "
        "change to this list."
    )


def test_the_allow_listed_fields_are_all_still_present_and_in_one_document() -> None:
    """The allow-list is not stale, and the surface has not silently moved.

    Without this, deleting `participation_outcome_counts` entirely would leave
    the test above green — it only checks that nothing was *added*. That would
    hide a manifest regeneration that dropped the field, which is a different
    defect but the same blind spot.
    """
    carriers = {
        path.name: _outcome_keyed_paths(json.loads(path.read_text(encoding="utf-8")))
        for path in _published_documents()
    }
    carrying = {name: paths for name, paths in carriers.items() if paths}

    assert len(carrying) == 1, (
        f"expected exactly one document to carry outcome-keyed fields, found: "
        f"{ {name: sorted(p) for name, p in carrying.items()} }"
    )
    (found_paths,) = carrying.values()
    assert found_paths == ALLOWED_OUTCOME_KEYED_PATHS, {
        "unexpectedly_absent": sorted(ALLOWED_OUTCOME_KEYED_PATHS - found_paths),
        "unexpectedly_present": sorted(found_paths - ALLOWED_OUTCOME_KEYED_PATHS),
    }


def test_the_probe_evidence_artifact_carries_no_outcome_keyed_field() -> None:
    """Named explicitly, because it is the reason this test scans a directory.

    `nba-injury-report-archive-reach-probe.json` publishes per-report
    `status_counts`. Those are **report designations**, which are the model's
    input, not participation outcomes, which are its target — so it is not a
    disclosure violation. Asserted rather than argued, so that a later edit
    adding an outcome breakdown to this file is caught here rather than in prose.
    """
    probe = ADAPTER_DOCS / "nba-injury-report-archive-reach-probe.json"
    assert probe.exists(), probe
    document = json.loads(probe.read_text(encoding="utf-8"))
    assert _outcome_keyed_paths(document) == set()

    # And it does carry status counts, so the assertion above is not vacuous
    # because the file happens to be empty of interesting fields.
    statuses = {
        status
        for observation in document["observations"]
        for status in observation.get("status_counts", {})
    }
    assert "out" in statuses and "probable" in statuses, sorted(statuses)
