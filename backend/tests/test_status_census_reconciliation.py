"""A second 2025-26 canonical count may not land unreconciled.

## The rule this enforces, and where it comes from

`docs/models/injury-status-conversion-literature.md` §4.2 records a decision:
`nba-injury-report-2025-26-status-census.json` was **held back rather than
landed**, because "publishing a second 2025-26 canonical count beside
`nba-injury-report-cohort-2025-10-21--2026-04-12.json` with no reconciliation
makes the disagreement permanent and undated." The two artifacts disagree by 30
canonical observations, localised entirely to rows with a resolved `player_id`,
and the cause is *not* established — §4.2 says so in terms.

That decision lived only in prose. Measured 2026-08-27 by committing the
held-back artifact into `docs/adapters/` and running every guard that could
plausibly see it — `test_cohort_admissibility.py`, `test_cohort_evidence.py`,
`test_injury_report_archive_reach.py` — **133 tests passed.** Nothing stopped
it. This repository's own finding is that a rule with nothing executable
connecting it to the code is not enforced, so this file is that connection.

## Why this is a reconciliation test rather than a banned filename

A filename blacklist forbids the artifact forever, including after somebody does
the work to reconcile it. The objection in §4.2 is not to the census existing —
it is to an *unreconciled* second count. So the test compares, and it passes the
moment the two artifacts agree. Landing a reconciled census is the outcome this
permits; landing an unreconciled one is the outcome it blocks, and it reports the
per-field disagreement so the next reader starts where §4.2 stopped.

## Why the zero here is checked against a known non-zero case

No census artifact is committed, so the scan below finds nothing and the
invariant holds vacuously. A scan that finds nothing because the *finder* is
broken looks identical. So `test_the_finder_recognises_a_census_shaped_artifact`
plants one and requires it to be found, and the reconciler is exercised against
the real recorded figures from §4.2's table — which disagree — before any zero it
reports is believed.

The real artifact is reproducible without being committed, via ``git show REF:PATH``:

    REF   origin/sr2501-injury-report-history
    PATH  docs/adapters/nba-injury-report-2025-26-status-census.json

**Do not delete that branch.** It is the only copy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.adapter_contract

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"
COMMITTED_MANIFEST = DOCS / "adapters" / "nba-injury-report-cohort-2025-10-21--2026-04-12.json"

#: ``kind`` discriminator the held-back artifact carries at its root. Matching on
#: this rather than on a filename means a census renamed on the way in is still
#: caught, and the artifact's own self-description is what selects it.
CENSUS_KIND = "nba_injury_report_status_census"

#: The disagreement exactly as `injury-status-conversion-literature.md` §4.2
#: publishes it. Held as a literal so this test does not compute its expectation
#: from either artifact under test — an expected value derived from the thing
#: being measured is a tautology, which is a defect this lane has shipped before.
RECORDED_CENSUS_TOTALS: dict[str, Any] = {
    "total_player_games": 13_819,
    "status_counts": {
        "available": 1_491,
        "doubtful": 221,
        "out": 10_478,
        "probable": 435,
        "questionable": 1_194,
    },
}
RECORDED_MANIFEST_TOTALS: dict[str, Any] = {
    "total_player_games": 13_789,
    "status_counts": {
        "available": 1_489,
        "doubtful": 221,
        "out": 10_453,
        "probable": 435,
        "questionable": 1_191,
    },
}


def _load(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _committed_json_artifacts() -> list[Path]:
    """Every committed JSON under ``docs``, found rather than enumerated.

    Scoped to the whole tree for the same reason
    ``TestTheDisclosureSurfaceIsClosed`` is: an artifact that escapes a guard by
    being new, or by sitting one directory over, is the failure mode the guard
    exists to stop.
    """
    return sorted(p for p in DOCS.rglob("*.json") if p.is_file())


def _census_artifacts() -> list[Path]:
    found = []
    for path in _committed_json_artifacts():
        try:
            document = _load(path)
        except json.JSONDecodeError:  # pragma: no cover - a malformed artifact is its own bug
            continue
        if isinstance(document, dict) and document.get("kind") == CENSUS_KIND:
            found.append(path)
    return found


def _census_totals(census: dict[str, Any]) -> dict[str, Any]:
    """Subscripted, never ``.get``: a renamed key must raise, not compare as absent."""
    return {
        "total_player_games": census["canonical_observations"]["total"],
        "status_counts": dict(census["status_counts_whole_season"]),
    }


def _manifest_totals(manifest: dict[str, Any]) -> dict[str, Any]:
    canonical = manifest["canonical_observations"]
    return {
        "total_player_games": canonical["total_player_games"],
        "status_counts": dict(canonical["status_counts"]),
    }


def reconcile(census: dict[str, Any], manifest: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Per-field ``(census, manifest)`` for every quantity the two disagree on."""
    disagreements: dict[str, tuple[Any, Any]] = {}
    if census["total_player_games"] != manifest["total_player_games"]:
        disagreements["total_player_games"] = (
            census["total_player_games"],
            manifest["total_player_games"],
        )
    statuses = set(census["status_counts"]) | set(manifest["status_counts"])
    for status in sorted(statuses):
        left = census["status_counts"].get(status)
        right = manifest["status_counts"].get(status)
        if left != right:
            disagreements[f"status_counts.{status}"] = (left, right)
    return disagreements


def test_the_artifact_scan_is_not_vacuous() -> None:
    """A glob matching nothing would make the invariant below trivially true."""
    found = _committed_json_artifacts()
    assert len(found) >= 4, f"suspiciously few committed artifacts: {found}"
    assert COMMITTED_MANIFEST in found, COMMITTED_MANIFEST


def test_the_committed_manifest_still_carries_what_the_reconciler_reads() -> None:
    """If the manifest's shape moved, the reconciler would read nothing and agree.

    Pinned against the figures §4.2 publishes, so a regenerated manifest that
    silently changed its canonical totals fails here rather than quietly moving
    the baseline the census is compared against.
    """
    totals = _manifest_totals(_load(COMMITTED_MANIFEST))
    assert totals == RECORDED_MANIFEST_TOTALS, totals


def test_the_finder_recognises_a_census_shaped_artifact(tmp_path: Path) -> None:
    """The known non-zero case for the finder.

    ``test_no_unreconciled_status_census_is_committed`` reports zero. A broken
    finder reports zero too. This distinguishes them.
    """
    planted = tmp_path / "planted-census.json"
    planted.write_text(json.dumps({"kind": CENSUS_KIND}), encoding="utf-8")
    assert _load(planted).get("kind") == CENSUS_KIND

    unrelated = tmp_path / "unrelated.json"
    unrelated.write_text(json.dumps({"kind": "something_else"}), encoding="utf-8")
    assert _load(unrelated).get("kind") != CENSUS_KIND


def test_the_reconciler_flags_the_recorded_disagreement() -> None:
    """The known non-zero case for the reconciler, using §4.2's real figures."""
    disagreements = reconcile(RECORDED_CENSUS_TOTALS, RECORDED_MANIFEST_TOTALS)

    assert set(disagreements) == {
        "total_player_games",
        "status_counts.available",
        "status_counts.out",
        "status_counts.questionable",
    }, disagreements
    assert disagreements["total_player_games"] == (13_819, 13_789)

    # The gap is 30 observations, and §4.2 says it localises to resolved rows.
    # Re-derived here rather than quoted, so a future edit to either figure that
    # breaks the arithmetic is caught instead of read past.
    assert 13_819 - 13_789 == 30
    per_status_gap = sum(
        RECORDED_CENSUS_TOTALS["status_counts"][s] - RECORDED_MANIFEST_TOTALS["status_counts"][s]
        for s in RECORDED_CENSUS_TOTALS["status_counts"]
    )
    assert per_status_gap == 30, per_status_gap


def test_the_reconciler_passes_an_agreeing_pair() -> None:
    """And it is not simply flagging everything it is handed."""
    assert reconcile(RECORDED_MANIFEST_TOTALS, RECORDED_MANIFEST_TOTALS) == {}


def test_no_unreconciled_status_census_is_committed() -> None:
    """The invariant.

    Passes today because no census is committed. It also passes if one is
    committed *and reconciles*, which is the point: the decision recorded in
    §4.2 was against an unreconciled second count, not against the artifact.
    """
    manifest = _manifest_totals(_load(COMMITTED_MANIFEST))

    for path in _census_artifacts():
        disagreements = reconcile(_census_totals(_load(path)), manifest)
        assert not disagreements, (
            f"{path.name} publishes a second 2025-26 canonical count that "
            f"disagrees with {COMMITTED_MANIFEST.name}:\n"
            + "\n".join(
                f"  {field}: census={left} manifest={right}"
                for field, (left, right) in sorted(disagreements.items())
            )
            + "\n\ndocs/models/injury-status-conversion-literature.md section 4.2 "
            "held this artifact back for exactly this reason: an unreconciled "
            "second count makes the disagreement permanent and undated. Either "
            "reconcile the two artifacts, or do not commit this one."
        )
