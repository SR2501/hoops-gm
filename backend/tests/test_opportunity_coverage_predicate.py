from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from hoops_gm.availability.opportunity_coverage import (
    CoveragePredicateNotEvaluable,
    evaluate_proceed_opportunity_coverage,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / "docs" / "models" / "participation-opportunity-coverage-v1-evidence-gap.json"
COUNT_FIELDS = (
    "total_opportunities",
    "direct_label_available",
    "confirmed_observed",
    "confirmed_absent",
    "unknown_opportunities",
)
REPORT_ONLY_COUNT_FIELDS = (
    "duplicate_opportunities",
    "unclassified_opportunities",
    "missing_required_provenance_fields",
)
EXPECTED_EVIDENCE_SHA256 = "57b2ca9636513e09706d5d59e5333ad1197fd3b62624e5cfe3c7be585d1053ad"


def _evidence() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(EVIDENCE.read_text(encoding="utf-8")))


def _lf_normalized(content: bytes) -> bytes:
    return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(_lf_normalized(path.read_bytes())).hexdigest()


def _cited_lines_sha256(path: Path, *, start_line: int, end_line: int) -> str:
    if start_line < 1 or end_line < start_line:
        raise ValueError("cited line range must be positive and ascending")
    lines = _lf_normalized(path.read_bytes()).splitlines(keepends=True)
    if end_line > len(lines):
        raise ValueError(f"cited line {end_line} exceeds {path}'s {len(lines)} lines")
    return hashlib.sha256(b"".join(lines[start_line - 1 : end_line])).hexdigest()


def _calculable_report(*, unknowns: tuple[int, int, int, int] = (5, 5, 5, 5)) -> dict[str, Any]:
    report = _evidence()
    report["required_input_artifacts"] = {
        "roster_source_registry_sha256": "1" * 64,
        "roster_reconstruction_contract_sha256": "2" * 64,
        "roster_interval_manifest_sha256": "3" * 64,
        "schedule_manifest_sha256": "4" * 64,
        "input_manifest_commit": "5" * 40,
        "classification_commit": "6" * 40,
        "cohort_key_sha256": "7" * 64,
    }
    verified_flags = (
        "roster_source_registry_sha256_is_verified",
        "roster_reconstruction_contract_sha256_is_verified",
        "roster_interval_manifest_sha256_is_verified",
        "schedule_manifest_sha256_is_verified",
        "roster_reconstruction_contract_independently_validated",
        "roster_interval_manifest_independently_reproduced",
        "schedule_manifest_independently_reproduced",
        "input_manifest_commit_is_ancestor_of_classification_commit",
        "classification_started_after_input_manifest_freeze",
        "cohort_key_sha256_is_reproduced",
        "roster_interval_coverage_complete",
        "schedule_coverage_complete",
    )
    for flag in verified_flags:
        report[flag] = True
    report["duplicate_opportunities"] = 0
    report["unclassified_opportunities"] = 0
    report["missing_required_provenance_fields"] = 0

    for season, unknown in zip(report["seasons"], unknowns, strict=True):
        season_report = report["seasons"][season]
        season_report.update(
            {
                "total_opportunities": 100,
                "direct_label_available": 100 - unknown,
                "confirmed_observed": 80 - unknown,
                "confirmed_absent": 20,
                "unknown_opportunities": unknown,
                "unknown_share": unknown / 100,
            }
        )

    season_reports = report["seasons"].values()
    for name in COUNT_FIELDS:
        report[name] = sum(season[name] for season in season_reports)
    report["unknown_share_overall"] = (
        report["unknown_opportunities"] / report["total_opportunities"]
    )
    return report


def _set_season_counts(report: dict[str, Any], season: str, *, total: int, unknown: int) -> None:
    report["seasons"][season].update(
        {
            "total_opportunities": total,
            "direct_label_available": total - unknown,
            "confirmed_observed": total - unknown,
            "confirmed_absent": 0,
            "unknown_opportunities": unknown,
            "unknown_share": unknown / total if total else 0.0,
        }
    )


def _recompute_overall_counts(report: dict[str, Any]) -> None:
    season_reports = report["seasons"].values()
    for name in COUNT_FIELDS:
        report[name] = sum(season[name] for season in season_reports)
    report["unknown_share_overall"] = (
        report["unknown_opportunities"] / report["total_opportunities"]
    )


def test_published_gap_is_not_evaluable_and_never_claims_zero() -> None:
    evidence = _evidence()

    assert evidence["evaluation_status"] == "not_evaluable"
    assert evidence["proceed_opportunity_coverage"] is None
    assert evidence["roster_interval_coverage_complete"] is False
    assert all(
        evidence[name] is None
        for name in (*COUNT_FIELDS, *REPORT_ONLY_COUNT_FIELDS, "unknown_share_overall")
    )
    assert all(
        season[name] is None
        for season in evidence["seasons"].values()
        for name in (*COUNT_FIELDS, "unknown_share")
    )

    with pytest.raises(CoveragePredicateNotEvaluable, match="roster interval coverage"):
        evaluate_proceed_opportunity_coverage(evidence)


def test_zero_denominator_raises_instead_of_passing_vacuously() -> None:
    vacuous = _calculable_report(unknowns=(0, 0, 0, 0))
    vacuous["total_opportunities"] = 0
    vacuous["direct_label_available"] = 0
    vacuous["confirmed_observed"] = 0
    vacuous["confirmed_absent"] = 0
    vacuous["unknown_opportunities"] = 0
    vacuous["unknown_share_overall"] = 0.0
    for season in vacuous["seasons"].values():
        season.update(
            {
                "total_opportunities": 0,
                "direct_label_available": 0,
                "confirmed_observed": 0,
                "confirmed_absent": 0,
                "unknown_opportunities": 0,
                "unknown_share": 0.0,
            }
        )

    assert vacuous["unknown_opportunities"] * 100 <= vacuous["total_opportunities"] * 5
    with pytest.raises(CoveragePredicateNotEvaluable, match="zero denominator is vacuous"):
        evaluate_proceed_opportunity_coverage(vacuous)


def test_one_zero_season_raises_even_when_the_overall_denominator_is_positive() -> None:
    vacuous_season = _calculable_report()
    _set_season_counts(vacuous_season, "2022-23", total=0, unknown=0)
    _recompute_overall_counts(vacuous_season)

    assert vacuous_season["total_opportunities"] > 0
    with pytest.raises(CoveragePredicateNotEvaluable, match=r"2022-23.*vacuous zero denominator"):
        evaluate_proceed_opportunity_coverage(vacuous_season)


def test_threshold_uses_the_preregistered_inclusive_integer_arithmetic() -> None:
    boundary = _calculable_report()
    assert evaluate_proceed_opportunity_coverage(boundary) is True

    season_over = _calculable_report(unknowns=(6, 4, 5, 5))
    assert season_over["unknown_opportunities"] * 100 == season_over["total_opportunities"] * 5
    assert evaluate_proceed_opportunity_coverage(season_over) is False

    overall_over = _calculable_report(unknowns=(6, 5, 5, 5))
    assert overall_over["unknown_opportunities"] * 100 > overall_over["total_opportunities"] * 5
    assert evaluate_proceed_opportunity_coverage(overall_over) is False

    rounding_trap = _calculable_report(unknowns=(0, 0, 0, 0))
    _set_season_counts(
        rounding_trap,
        "2022-23",
        total=20_000_000_000_000_000_000 - 1,
        unknown=1_000_000_000_000_000_000,
    )
    _recompute_overall_counts(rounding_trap)
    assert rounding_trap["seasons"]["2022-23"]["unknown_share"] == 0.05
    assert evaluate_proceed_opportunity_coverage(rounding_trap) is False


def test_report_shape_and_exact_shares_are_part_of_the_predicate() -> None:
    wrong_share = _calculable_report()
    wrong_share["unknown_share_overall"] = 0.0
    assert evaluate_proceed_opportunity_coverage(wrong_share) is False

    bool_count = _calculable_report()
    bool_count["unknown_opportunities"] = False
    with pytest.raises(CoveragePredicateNotEvaluable, match="not an integer"):
        evaluate_proceed_opportunity_coverage(bool_count)

    bool_share = _calculable_report(unknowns=(0, 0, 0, 0))
    bool_share["unknown_share_overall"] = False
    for season in bool_share["seasons"].values():
        season["unknown_share"] = False
    with pytest.raises(CoveragePredicateNotEvaluable, match="not numeric"):
        evaluate_proceed_opportunity_coverage(bool_share)


def test_verified_flags_cannot_authorize_null_provenance() -> None:
    contradictory = _calculable_report()
    for field in contradictory["required_input_artifacts"]:
        contradictory["required_input_artifacts"][field] = None

    with pytest.raises(CoveragePredicateNotEvaluable) as exc_info:
        evaluate_proceed_opportunity_coverage(contradictory)

    for field in contradictory["required_input_artifacts"]:
        assert any(
            f"required_input_artifacts.{field} is missing" in reason
            and "contradicts its bound evidence" in reason
            for reason in exc_info.value.reasons
        )


@pytest.mark.parametrize("malformed", [True, 123, "A" * 64, "a" * 63])
def test_verified_hash_must_be_a_lowercase_sha256(malformed: object) -> None:
    contradictory = _calculable_report()
    contradictory["required_input_artifacts"]["roster_source_registry_sha256"] = malformed

    with pytest.raises(
        CoveragePredicateNotEvaluable,
        match=r"roster_source_registry_sha256.*not a 64-character lowercase hexadecimal SHA-256",
    ):
        evaluate_proceed_opportunity_coverage(contradictory)


@pytest.mark.parametrize("malformed", [True, 123, "A" * 40, "a" * 39])
def test_bound_commit_must_be_a_full_lowercase_git_object_id(malformed: object) -> None:
    contradictory = _calculable_report()
    contradictory["required_input_artifacts"]["classification_commit"] = malformed

    with pytest.raises(
        CoveragePredicateNotEvaluable,
        match=r"classification_commit.*not a 40-character lowercase hexadecimal Git commit",
    ):
        evaluate_proceed_opportunity_coverage(contradictory)


def test_evidence_citations_are_bound_to_the_exact_committed_files() -> None:
    evidence = _evidence()

    assert _lf_sha256(EVIDENCE) == EXPECTED_EVIDENCE_SHA256, (
        f"{EVIDENCE.name} has itself changed. It is frozen v1 evidence: its digest is "
        "pinned here, and the v2 carry note forbids retrofitting anything into v1. If a "
        "citation below has gone stale, the remedy is to move your content - never to "
        "re-record the evidence so it follows the move."
    )
    for citation in evidence["evidence"]:
        assert (
            _cited_lines_sha256(
                REPO_ROOT / citation["path"],
                start_line=citation["start_line"],
                end_line=citation["end_line"],
            )
            == citation["sha256_lf_normalized_cited_lines"]
        ), (
            f"the frozen evidence cites {citation['path']} lines {citation['start_line']}-"
            f"{citation['end_line']} by hash, and those lines no longer hash to what was "
            "recorded. The usual cause is not an edit to the cited prose at all: it is an "
            f"insertion ANYWHERE ABOVE line {citation['start_line']} of that file, which "
            "shifts the cited block down so the same line numbers now address different "
            "text. docs/backlog.md is cited this way and is the most-edited file in the "
            "repository, so adding an item near its top trips this while leaving the "
            "quoted evidence untouched. Put the content BELOW the cited range - the last "
            "backlog item sits below it - or in docs/handoff.md, which is not cited at "
            "all. Do not adjust the recorded line numbers or hashes to match: the "
            "evidence is frozen, and this assertion is the only thing standing between a "
            "shifted citation and a Model gate quoting prose it no longer points at."
        )
    for census in evidence["direct_censuses"].values():
        assert _lf_sha256(REPO_ROOT / census["path"]) == census["sha256_lf_normalized"], (
            f"the direct census {census['path']} has changed since it was frozen. These "
            "are whole-file digests, so any edit anywhere in the file trips this, and the "
            "same rule applies: move the content, do not re-record the census."
        )


def test_evidence_digests_are_independent_of_checkout_line_endings(tmp_path: Path) -> None:
    lf = tmp_path / "lf.md"
    crlf = tmp_path / "crlf.md"
    text = "before\ncited one\ncited two\nafter\n"
    lf.write_bytes(text.encode("utf-8"))
    crlf.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))

    assert _cited_lines_sha256(lf, start_line=2, end_line=3) == _cited_lines_sha256(
        crlf, start_line=2, end_line=3
    )
    assert _lf_sha256(lf) == _lf_sha256(crlf)


def test_cited_line_digest_ignores_appends_after_the_range(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog.md"
    backlog.write_text("before\ncited\n", encoding="utf-8")
    before = _cited_lines_sha256(backlog, start_line=2, end_line=2)

    # This stability is safe for the real backlog citation only because backlog.md
    # is append-only and the cited passage precedes its append point.
    backlog.write_text("before\ncited\nlater append\n", encoding="utf-8")

    assert _cited_lines_sha256(backlog, start_line=2, end_line=2) == before


def test_mutating_a_required_preclassification_flag_cannot_proceed() -> None:
    report = _calculable_report()
    report["schedule_manifest_independently_reproduced"] = False

    assert evaluate_proceed_opportunity_coverage(copy.deepcopy(report)) is False
