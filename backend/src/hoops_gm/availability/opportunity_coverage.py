"""Fail-closed evaluation of the frozen opportunity-coverage predicate.

The v1 preregistration requires a complete, independently reproduced roster
interval manifest before a player-game cohort exists. A missing denominator is
not a zero denominator: the former is not calculable, while the latter would
make the integer threshold comparison ``0 <= 0`` vacuously true.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, cast

PREREGISTRATION_ID: Final = "participation-opportunity-coverage-v1-20260906T052618Z"
POPULATION: Final = "all_at_risk_player_games"
COHORT_RULE: Final = "roster_interval_start_inclusive_end_exclusive_at_tipoff_v1"
REQUIRED_WINDOWS: Final[dict[str, tuple[str, str]]] = {
    "2022-23": ("2022-10-18", "2023-04-09"),
    "2023-24": ("2023-10-24", "2024-04-14"),
    "2024-25": ("2024-10-22", "2025-04-13"),
    "2025-26": ("2025-10-21", "2026-04-12"),
}

_TOP_LEVEL_COUNTS: Final = (
    "total_opportunities",
    "direct_label_available",
    "confirmed_observed",
    "confirmed_absent",
    "unknown_opportunities",
    "duplicate_opportunities",
    "unclassified_opportunities",
    "missing_required_provenance_fields",
)
_SEASON_COUNTS: Final = (
    "total_opportunities",
    "direct_label_available",
    "confirmed_observed",
    "confirmed_absent",
    "unknown_opportunities",
)
_VERIFIED_INPUT_FLAGS: Final = (
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


class CoveragePredicateNotEvaluable(ValueError):
    """The report has no valid, positive player-game denominator."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("PROCEED_OPPORTUNITY_COVERAGE not evaluable: " + "; ".join(self.reasons))


def evaluate_proceed_opportunity_coverage(report: Mapping[str, object]) -> bool:
    """Evaluate the canonical v1 predicate only after its cohort exists.

    The threshold comparisons intentionally retain the preregistered integer
    arithmetic. They are never replaced by float comparisons.
    """

    seasons = _mapping(report.get("seasons"), "seasons")
    reasons = _non_evaluable_reasons(report, seasons)
    if reasons:
        raise CoveragePredicateNotEvaluable(reasons)

    top_counts = {name: _integer(report[name], name) for name in _TOP_LEVEL_COUNTS}
    season_counts = {
        season: {
            name: _integer(_mapping(seasons[season], f"seasons.{season}")[name], name)
            for name in _SEASON_COUNTS
        }
        for season in REQUIRED_WINDOWS
    }

    total = top_counts["total_opportunities"]
    unknown = top_counts["unknown_opportunities"]
    direct = top_counts["direct_label_available"]
    observed = top_counts["confirmed_observed"]
    absent = top_counts["confirmed_absent"]

    return (
        report.get("preregistration_id") == PREREGISTRATION_ID
        and report.get("population") == POPULATION
        and set(seasons) == set(REQUIRED_WINDOWS)
        and all(
            (
                _mapping(seasons[season], f"seasons.{season}").get("start_date"),
                _mapping(seasons[season], f"seasons.{season}").get("end_date"),
            )
            == window
            for season, window in REQUIRED_WINDOWS.items()
        )
        and report.get("cohort_rule") == COHORT_RULE
        and all(report.get(flag) is True for flag in _VERIFIED_INPUT_FLAGS)
        and report.get("all_four_direct_censuses_present") is True
        and top_counts["duplicate_opportunities"] == 0
        and top_counts["unclassified_opportunities"] == 0
        and top_counts["missing_required_provenance_fields"] == 0
        and all(value >= 0 for value in top_counts.values())
        and all(value >= 0 for counts in season_counts.values() for value in counts.values())
        and total > 0
        and total == direct + unknown
        and direct == observed + absent
        and total == sum(counts["total_opportunities"] for counts in season_counts.values())
        and direct == sum(counts["direct_label_available"] for counts in season_counts.values())
        and observed == sum(counts["confirmed_observed"] for counts in season_counts.values())
        and absent == sum(counts["confirmed_absent"] for counts in season_counts.values())
        and unknown == sum(counts["unknown_opportunities"] for counts in season_counts.values())
        and report.get("unknown_share_overall") == unknown / total
        and unknown * 100 <= total * 5
        and all(
            _season_predicate(_mapping(seasons[season], f"seasons.{season}"), season_counts[season])
            for season in REQUIRED_WINDOWS
        )
    )


def _non_evaluable_reasons(
    report: Mapping[str, object], seasons: Mapping[str, object]
) -> list[str]:
    reasons: list[str] = []
    if report.get("roster_interval_coverage_complete") is not True:
        reasons.append("roster interval coverage is incomplete")

    for name in _TOP_LEVEL_COUNTS:
        _append_count_problem(reasons, report.get(name), name)
    for season in REQUIRED_WINDOWS:
        season_value = seasons.get(season)
        if not isinstance(season_value, Mapping):
            reasons.append(f"season {season} is missing")
            continue
        season_report = cast(Mapping[str, object], season_value)
        for name in _SEASON_COUNTS:
            _append_count_problem(reasons, season_report.get(name), f"seasons.{season}.{name}")
        _append_share_problem(
            reasons, season_report.get("unknown_share"), f"seasons.{season}.unknown_share"
        )
        season_total = season_report.get("total_opportunities")
        if type(season_total) is int and season_total == 0:
            reasons.append(f"seasons.{season}.total_opportunities is a vacuous zero denominator")

    _append_share_problem(reasons, report.get("unknown_share_overall"), "unknown_share_overall")

    total = report.get("total_opportunities")
    if type(total) is int and total == 0:
        reasons.append("zero denominator is vacuous and cannot authorize evaluation")
    return reasons


def _append_count_problem(reasons: list[str], value: object, path: str) -> None:
    if value is None:
        reasons.append(f"{path} is not calculable")
    elif type(value) is not int:
        reasons.append(f"{path} is not an integer")
    elif value < 0:
        reasons.append(f"{path} is negative")


def _append_share_problem(reasons: list[str], value: object, path: str) -> None:
    if value is None:
        reasons.append(f"{path} is not calculable")
    elif type(value) not in (int, float):
        reasons.append(f"{path} is not numeric")


def _season_predicate(report: Mapping[str, object], counts: Mapping[str, int]) -> bool:
    total = counts["total_opportunities"]
    unknown = counts["unknown_opportunities"]
    direct = counts["direct_label_available"]
    return (
        total > 0
        and total == direct + unknown
        and direct == counts["confirmed_observed"] + counts["confirmed_absent"]
        and report.get("unknown_share") == unknown / total
        and unknown * 100 <= total * 5
    )


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CoveragePredicateNotEvaluable((f"{path} is missing or not an object",))
    return cast(Mapping[str, object], value)


def _integer(value: object, path: str) -> int:
    if type(value) is not int:
        raise CoveragePredicateNotEvaluable((f"{path} is not an integer",))
    return value
