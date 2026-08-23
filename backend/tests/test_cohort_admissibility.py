"""The pre-unblind disclosure surface is a closed set, enforced in CI.

``docs/models/injury-status-conversion-preregistration.md`` §2 states the
constraint that protects the frozen protocol:

    The pre-unblind disclosure surface carries **no outcome-valued count beyond
    the single whole-cohort ``participation_outcome_counts`` the manifest
    already contains**. **No new outcome-keyed field may be added, at any
    granularity, in any manifest version.**

A granularity rule was tried first — "outcome-valued counts stay whole-cohort;
only denominators get the finer breakdown" — and both reviewers showed it is
necessary but not sufficient. Three reasons, none hypothetical:

- it constrains coarseness rather than informativeness;
- it is stated per-manifest, and git makes cross-manifest differencing free, so
  widening the same window yields cohort B superset of cohort A with both
  committed and the added dates' outcome marginal falling out by subtraction;
- "whole-cohort" is a label, not a size guarantee.

So the rule is a closed set, and a closed set is testable. These tests are that
test. **They fail when the set grows**, which is the only behaviour that makes
the gate mean anything: a reviewer who adds an outcome-keyed field to any
committed cohort artifact must come here and change a frozen constant, in a
diff that says so.

These are offline and read committed artifacts only. No store, no network.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from hoops_gm.db.models.enums import DnpReason, ParticipationOutcome
from hoops_gm.ingest.injury_report.client import FIFTEEN_MINUTE_ERA_START
from hoops_gm.ingest.injury_report.cohort_admissibility import (
    ADMISSIBILITY_FLOOR,
    COHORT_STATUSES,
    DIRECT_OUTCOMES,
    ERA_LEGACY,
    ERA_SHORT_LEAD,
    LEAD_TIME_BANDS,
    OUTCOME_KEYED_MANIFEST_FIELDS,
    CrossStoreTipoffAgreement,
    chronological_split,
    lead_time_band,
    outcome_keyed_field_paths,
    read_only_engine,
    reconcile_tipoffs_across_stores,
    report_era,
)

pytestmark = pytest.mark.adapter_contract

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTERS = REPO_ROOT / "docs" / "adapters"
COHORT_MANIFEST = ADAPTERS / "nba-injury-report-cohort-2025-12-08--2026-01-04.json"
LEDGER_COVERAGE = ADAPTERS / "participation-ledger-2025-26-coverage.json"
ADMISSIBILITY = ADAPTERS / "nba-injury-report-cohort-admissibility-2025-26.json"


def _load(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _committed_evidence_artifacts() -> list[Path]:
    """**Every** committed JSON evidence artifact, found rather than enumerated.

    Scoped to the whole ``docs`` tree on purpose. Enumerating files by name — or
    globbing only ``nba-injury-report-cohort*`` as an earlier version did — lets
    a *new* artifact escape the closed set simply by being new, which is the
    exact failure mode the set exists to stop. The coordinator ruled this before
    a second artefact could exploit it, and the gap was already real:
    ``participation-ledger-2025-26-coverage.json`` publishes an outcome marginal
    and sat entirely outside the old cohort-scoped glob.
    """
    return sorted(p for p in (REPO_ROOT / "docs").rglob("*.json") if p.is_file())


def _surface(path: Path) -> set[tuple[str, str]]:
    return {
        (path.name, field)
        for field in outcome_keyed_field_paths(_load(path), normalize_indices=True)
    }


class TestTheDisclosureSurfaceIsClosed:
    def test_the_scan_actually_finds_artifacts(self) -> None:
        # A glob that silently matches nothing would make every test below
        # vacuously green -- the same class of false zero as an empty database.
        found = _committed_evidence_artifacts()
        assert len(found) >= 4, f"suspiciously few evidence artifacts: {found}"

    def test_the_scan_covers_both_allow_listed_files(self) -> None:
        # The allow-list names two files. If either stopped being discovered,
        # the union test below would pass while the guard watched nothing.
        discovered = {p.name for p in _committed_evidence_artifacts()}
        assert {name for name, _ in OUTCOME_KEYED_MANIFEST_FIELDS} <= discovered

    def test_the_union_over_the_whole_surface_equals_the_frozen_set(self) -> None:
        union: set[tuple[str, str]] = set()
        for path in _committed_evidence_artifacts():
            union |= _surface(path)
        assert union == set(OUTCOME_KEYED_MANIFEST_FIELDS), (
            "the pre-unblind outcome-keyed disclosure surface changed. §2 of the "
            "frozen preregistration forbids adding an outcome-keyed field at any "
            "granularity, in any artifact. If this is deliberate, it needs the "
            "owner and a preregistration amendment, not a constant edit.\n"
            f"  added:   {sorted(union - set(OUTCOME_KEYED_MANIFEST_FIELDS))}\n"
            f"  removed: {sorted(set(OUTCOME_KEYED_MANIFEST_FIELDS) - union)}"
        )

    def test_the_admissibility_artifact_adds_no_outcome_keyed_field(self) -> None:
        assert _surface(ADMISSIBILITY) == set()

    def test_every_allow_listed_field_is_still_present_where_it_was(self) -> None:
        # The allow-list is an upper bound, so a shrinking surface would pass
        # the union test's superset half. Pin presence too: a regenerated
        # artifact that silently dropped inherited adapter evidence is also a
        # change worth failing on.
        for name, field in OUTCOME_KEYED_MANIFEST_FIELDS:
            path = REPO_ROOT / "docs" / "adapters" / name
            assert path.is_file(), f"allow-listed artifact vanished: {name}"
            assert (name, field) in _surface(path)


class TestTheEraCompositionTheCountCannotSee:
    """§2 is pooled over the holdout, so it is blind to era composition.

    ``FIFTEEN_MINUTE_ERA_START`` is 2025-12-22 Eastern and falls **inside** a
    season-scale cohort. ADR-007 records the regimes differing at 1.596
    unresolved `doubtful` per date short-lead against 0.917 legacy, and
    unresolved rows are *excluded* — so the exclusion rate is era-dependent and
    concentrated on the scarcest status. Published as denominators, which costs
    no unblind.
    """

    def test_the_boundary_constant_is_where_the_artifact_says_it_is(self) -> None:
        # The artifact quotes the boundary as prose. Re-derive it from the
        # constant rather than trusting the string.
        assert FIFTEEN_MINUTE_ERA_START.date() == date(2025, 12, 22)
        assert report_era(datetime(2025, 12, 20, 22, 30, tzinfo=UTC)) == ERA_LEGACY
        assert report_era(datetime(2026, 1, 5, 22, 30, tzinfo=UTC)) == ERA_SHORT_LEAD

    def test_the_boundary_is_classified_by_report_time_not_game_date(self) -> None:
        # An evening-before report for a 2025-12-22 game is filed 2025-12-21
        # and is legacy. Classifying by game date would mislabel exactly the
        # boundary rows the composition exists to expose.
        evening_before = datetime(2025, 12, 21, 22, 30, tzinfo=UTC)  # 17:30 ET
        assert report_era(evening_before) == ERA_LEGACY

    def test_the_boundary_falls_inside_the_committed_cohort(self) -> None:
        scope = _load(ADMISSIBILITY)["scope"]
        start = date.fromisoformat(scope["start_game_date"])
        end = date.fromisoformat(scope["end_game_date"])
        assert start < FIFTEEN_MINUTE_ERA_START.date() < end, (
            "if the era boundary ever falls outside the cohort this whole "
            "section is moot -- and the composition below would be trivially "
            "one-sided rather than meaningfully mixed"
        )

    def test_the_per_partition_composition_is_published(self) -> None:
        section = _load(ADMISSIBILITY)["section_2_admissibility"]
        composition = section["era_composition_by_partition"]
        assert set(composition) == {"development", "held_out", "selection"}
        for partition in composition.values():
            assert set(partition) == {ERA_LEGACY, ERA_SHORT_LEAD}

    def test_the_holdout_contains_none_of_the_legacy_regime(self) -> None:
        # The finding itself, pinned. If a future cohort or split makes this
        # false, that is good news and this test should be updated to say so --
        # but it must not change silently.
        composition = _load(ADMISSIBILITY)["section_2_admissibility"][
            "era_composition_by_partition"
        ]
        assert composition["held_out"][ERA_LEGACY] == 0
        assert composition["held_out"][ERA_SHORT_LEAD] > 0
        assert composition["development"][ERA_LEGACY] > 0

    def test_the_composition_reconciles_with_the_by_date_era_table(self) -> None:
        artifact = _load(ADMISSIBILITY)
        by_date = artifact["direct_outcomes_by_report_era"]["by_game_date"]
        section = artifact["section_2_admissibility"]
        _dev, _sel, hold = chronological_split(
            [date.fromisoformat(d) for d in artifact["direct_outcome_counts_by_game_date"]]
        )
        recomputed = {ERA_LEGACY: 0, ERA_SHORT_LEAD: 0}
        for day in hold:
            for era, count in by_date.get(day.isoformat(), {}).items():
                recomputed[era] += count
        assert recomputed == section["era_composition_by_partition"]["held_out"]

    def test_the_era_table_totals_match_the_direct_totals(self) -> None:
        artifact = _load(ADMISSIBILITY)
        by_status = artifact["direct_outcomes_by_report_era"]["by_status"]
        direct = artifact["section_2_admissibility"]["direct_outcomes_by_status"]
        for status in COHORT_STATUSES:
            assert sum(era.get(status, 0) for era in by_status.values()) == direct[status]

    def test_the_era_table_is_partition_agnostic(self) -> None:
        # ADR-008: a split boundary is an availability-layer parameter and must
        # not be baked into an observations-layer payload. The by-date table
        # carries no partition label; only the derived §2 block does.
        by_date = _load(ADMISSIBILITY)["direct_outcomes_by_report_era"]["by_game_date"]
        blob = json.dumps(by_date)
        for word in ("development", "selection", "held_out", "holdout"):
            assert word not in blob

    def test_the_adr_007_figure_does_not_replicate_and_that_is_recorded(self) -> None:
        # Pinned because a non-replication is a finding, and an unpinned one
        # quietly reverts to the inherited number. This asserts the SHAPE of
        # the disagreement, not that ADR-007 is wrong -- the two count
        # different populations and the artifact says so.
        era = _load(ADMISSIBILITY)["direct_outcomes_by_report_era"]
        per_era = era["unresolved_identity_exclusions_by_era_and_status"]
        dates = era["game_dates_by_era"]
        rates = {name: per_era.get(name, {}).get("doubtful", 0) / dates[name] for name in dates}
        assert rates[ERA_SHORT_LEAD] < 0.1
        assert rates[ERA_LEGACY] < 0.1
        assert "DOES NOT REPLICATE HERE" in era["adr_007_replication_note"]

    def test_unresolved_exclusions_do_not_concentrate_on_doubtful(self) -> None:
        per_era = _load(ADMISSIBILITY)["direct_outcomes_by_report_era"][
            "unresolved_identity_exclusions_by_era_and_status"
        ]
        for tally in per_era.values():
            assert tally.get("doubtful", 0) < tally.get("out", 0)


class TestTheLimitationsAreDeclaredPreUnblind:
    def test_the_end_of_season_holdout_limitation_is_stated(self) -> None:
        section = _load(ADMISSIBILITY)["section_2_admissibility"]
        limitations = section["limitations_that_the_count_cannot_see"]
        joined = " ".join(limitations)
        assert "END-OF-SEASON SHUTDOWN WINDOW" in joined
        assert "NOT THE REGIME THE TOOL IS USED IN" in joined
        assert "MODEL CARD VERBATIM" in joined

    def test_the_era_limitation_is_stated(self) -> None:
        limitations = _load(ADMISSIBILITY)["section_2_admissibility"][
            "limitations_that_the_count_cannot_see"
        ]
        assert any("REPORTING-ERA BOUNDARY" in item for item in limitations)

    def test_the_split_boundaries_were_not_moved_to_dodge_them(self) -> None:
        # §4 names the trap: choosing different proportions BECAUSE these ones
        # are inconvenient is a worse reason than keeping them. The declared
        # split must still be the frozen 50/25/25 floor rule.
        artifact = _load(ADMISSIBILITY)
        section = artifact["section_2_admissibility"]
        n = artifact["scope"]["game_dates"]
        assert section["split_game_dates"]["development"] == int(n * 0.50)
        assert section["split_game_dates"]["selection"] == int(n * 0.25)
        assert section["split_game_dates"]["held_out"] == n - int(n * 0.50) - int(n * 0.25)


class TestComparabilityIsStatedRatherThanSoftened:
    """The one thing the headline number must not be read without.

    Owner ruling 2026-08-23: the discrepancy against the committed manifest
    does not reverse the verdict, and is *also* not to be waved away. These
    pin the honest statement in place so a later edit cannot quietly soften it
    into "broadly consistent".
    """

    def test_non_comparability_is_declared_not_implied(self) -> None:
        block = _load(ADMISSIBILITY)["comparability_to_committed_manifest"]
        assert block["directly_comparable"] is False
        assert "NOT DIRECTLY COMPARABLE" in block["statement"]

    def test_the_driven_and_reasoned_halves_are_kept_apart(self) -> None:
        # The whole value of this block is that it does not present a reasoned
        # claim as a measured one.
        block = _load(ADMISSIBILITY)["comparability_to_committed_manifest"]
        assert "88 distinct report timestamps" in block["driven_explanation"]
        assert "judgement, not a measurement" in block["reasoned_not_driven"]

    def test_the_v1_veto_confirmation_is_recorded(self) -> None:
        # Confirming the four-week cohort was correctly refused is worth as
        # much as the admissibility result: it is evidence this pipeline can
        # disagree with the protocol and did not.
        block = _load(ADMISSIBILITY)["comparability_to_committed_manifest"]
        assert "0.3219" in block["v1_veto_independently_confirmed"]
        assert "correctly refused" in block["v1_veto_independently_confirmed"]

    def test_it_adds_no_outcome_keyed_field(self) -> None:
        assert _surface(ADMISSIBILITY) == set()


class TestOutcomeKeyedDetection:
    def test_the_two_enums_collide_on_exactly_one_token(self) -> None:
        # Justifies the `seasons[].reasons` allow-list entry. That field is
        # DnpReason-keyed, not outcome-keyed, and only trips the detector
        # because `not_with_team` is a member of both enums. If the overlap
        # ever grows, the entry's rationale no longer holds and this fails.
        overlap = {o.value for o in ParticipationOutcome} & {r.value for r in DnpReason}
        assert overlap == {"not_with_team"}

    def test_the_reasons_field_is_dnp_reason_keyed_not_outcome_keyed(self) -> None:
        reasons = _load(LEDGER_COVERAGE)["seasons"][0]["reasons"]
        assert set(reasons) <= {r.value for r in DnpReason}
        # Its keys are NOT a subset of the outcome vocabulary, which is what
        # distinguishes it from a genuine outcome marginal.
        assert not set(reasons) <= {o.value for o in ParticipationOutcome}

    def test_detects_a_nested_outcome_marginal(self) -> None:
        doc = {"a": {"b": {"played": 3, "inactive": 1}}}
        assert outcome_keyed_field_paths(doc) == {"a.b"}

    def test_detects_by_intersection_not_subset(self) -> None:
        # A subset test passes this. That is the evasion: hide one outcome key
        # among unrelated ones and the mapping is no longer a pure marginal.
        doc = {"counts": {"played": 3, "game_dates": 26}}
        assert outcome_keyed_field_paths(doc) == {"counts"}

    def test_finds_an_outcome_marginal_inside_a_list(self) -> None:
        doc = {"per_date": [{"date": "2026-01-01", "tally": {"did_not_dress": 2}}]}
        assert outcome_keyed_field_paths(doc) == {"per_date[0].tally"}

    def test_status_keyed_mappings_are_not_outcome_keyed(self) -> None:
        # The two vocabularies are disjoint, which is what makes a by-status
        # breakdown publishable and a by-outcome one not.
        doc = {"held_out": dict.fromkeys(COHORT_STATUSES, 30)}
        assert outcome_keyed_field_paths(doc) == frozenset()

    def test_the_two_vocabularies_do_not_overlap(self) -> None:
        outcomes = {o.value for o in ParticipationOutcome}
        assert outcomes & set(COHORT_STATUSES) == set()

    def test_unknown_is_not_a_direct_outcome(self) -> None:
        # R35: a silent ledger is not an absence. If UNKNOWN ever counted as
        # direct, non-direct rows would enter the fitting denominator and §1
        # excludes them.
        assert ParticipationOutcome.UNKNOWN.value not in DIRECT_OUTCOMES
        assert len(DIRECT_OUTCOMES) == len(ParticipationOutcome) - 1


class TestTheSplitRule:
    """§4: ordered distinct game dates, floor rules, holdout as remainder."""

    def test_reproduces_the_documented_v1_boundaries(self) -> None:
        # §4 records that floor(0.50 * 25) = 12 and floor(0.25 * 25) = 6 recover
        # v1's realized split exactly. That is the check that shows the rule is
        # inherited rather than rediscovered, so it is worth pinning.
        dates = [date(2025, 12, 8) + timedelta(days=i) for i in range(25)]
        dev, sel, hold = chronological_split(dates)
        assert (len(dev), len(sel), len(hold)) == (12, 6, 7)
        assert dev[-1] == dates[11]
        assert sel[-1] == dates[17]

    def test_partitions_are_exhaustive_and_disjoint(self) -> None:
        for n in range(0, 200):
            dates = [date(2025, 10, 21) + timedelta(days=i) for i in range(n)]
            dev, sel, hold = chronological_split(dates)
            assert len(dev) + len(sel) + len(hold) == n
            assert set(dev) | set(sel) | set(hold) == set(dates)
            assert not (set(dev) & set(sel))
            assert not (set(sel) & set(hold))
            assert not (set(dev) & set(hold))

    def test_boundaries_never_fall_inside_a_date(self) -> None:
        dates = [date(2025, 10, 21) + timedelta(days=i) for i in range(164)]
        dev, sel, hold = chronological_split(dates)
        assert max(dev) < min(sel) < min(hold)

    def test_input_order_does_not_matter(self) -> None:
        dates = [date(2026, 1, 5), date(2025, 12, 1), date(2026, 3, 2), date(2025, 11, 9)]
        assert chronological_split(dates) == chronological_split(sorted(dates, reverse=True))


class TestLeadTimeBands:
    def test_every_band_boundary_is_covered_without_gap_or_overlap(self) -> None:
        for minutes in range(0, 2000):
            assert lead_time_band(minutes) in {b[0] for b in LEAD_TIME_BANDS}

    def test_the_documented_boundaries_land_in_the_documented_bands(self) -> None:
        assert lead_time_band(60) == "<=60"
        assert lead_time_band(61) == "61-180"
        assert lead_time_band(180) == "61-180"
        assert lead_time_band(181) == "181-540"
        assert lead_time_band(540) == "181-540"
        assert lead_time_band(541) == ">540"

    def test_the_widened_cohort_falsifies_the_expected_empty_band(self) -> None:
        # §7 expects `>540` empty "on any joinable data resembling the current
        # cohort". The widened cohort does not resemble it: the committed
        # four-week manifest caps joined lead time at 540, and the season-scale
        # artifact reaches beyond it. Pinned so the finding cannot quietly
        # revert to the old expectation.
        artifact = _load(ADMISSIBILITY)
        assert artifact["lead_time_minutes"]["direct"]["maximum"] > 540
        assert artifact["direct_outcomes_by_lead_time_band"][">540"]


class TestTheCrossStoreTipoffCheck:
    """The join is only sound while the two stores agree on every instant."""

    def test_disagreeing_instants_are_reported_and_refuse_agreement(self) -> None:
        a = datetime(2026, 1, 2, 0, 30)
        b = datetime(2026, 1, 2, 1, 30)
        result = reconcile_tipoffs_across_stores(
            {"0022500001": (a, date(2026, 1, 1))},
            {"0022500001": (b, date(2026, 1, 1))},
        )
        assert result.compared == 1
        assert not result.agreed
        assert "0022500001" in result.disagreements

    def test_a_shifted_game_date_refuses_agreement_on_its_own(self) -> None:
        # AGENTS.md: `gameEt` carries a `Z` and is not UTC. That defect shifts
        # game_date for every game tipping after 7pm Eastern while leaving the
        # instant itself parseable, so the date needs its own witness.
        instant = datetime(2026, 1, 2, 0, 30)
        result = reconcile_tipoffs_across_stores(
            {"0022500001": (instant, date(2026, 1, 1))},
            {"0022500001": (instant, date(2026, 1, 2))},
        )
        assert not result.agreed
        assert result.disagreements == {}
        assert "0022500001" in result.date_disagreements

    def test_games_compared_nowhere_agree_perfectly_and_witness_nothing(self) -> None:
        result = reconcile_tipoffs_across_stores(
            {"0022500259": (None, date(2025, 11, 19))},
            {"0022500259": (datetime(2025, 11, 20, 1, 0), date(2025, 11, 19))},
        )
        assert result.agreed
        assert not result.witnessed
        assert result.absent == ("0022500259",)

    def test_the_committed_artifact_witnessed_its_agreement(self) -> None:
        summary = _load(ADMISSIBILITY)["cross_store_tipoff_agreement"]
        assert summary["agreed"]
        assert summary["witnessed"]
        assert summary["games_compared"] > 0
        assert summary["tipoff_disagreements"] == {}
        assert summary["game_date_disagreements"] == {}

    def test_summary_carries_both_agreed_and_witnessed(self) -> None:
        empty = CrossStoreTipoffAgreement(
            compared=0, absent=(), disagreements={}, date_disagreements={}
        )
        summary = empty.as_summary()
        assert summary["agreed"] is True
        assert summary["witnessed"] is False


class TestTheStoreIsNotCreatedByLookingAtIt:
    def test_a_missing_path_refuses_rather_than_creating_a_database(self, tmp_path: Path) -> None:
        # SQLite creates on connect. A mistyped path would otherwise yield a
        # new empty file and an honest, reproducible, meaningless zero -- a
        # false zero manufactured by the check written to settle the question.
        missing = tmp_path / "not-here.db"
        with pytest.raises(FileNotFoundError):
            read_only_engine(missing)
        assert not missing.exists(), "the probe created the database it was checking for"

    def test_a_directory_is_refused_too(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_only_engine(tmp_path)


class TestTheCommittedAdmissibilityArtifact:
    def test_records_the_verdict_against_the_declared_floor(self) -> None:
        section = _load(ADMISSIBILITY)["section_2_admissibility"]
        assert section["floor"] == ADMISSIBILITY_FLOOR
        assert section["unit"] == "direct outcomes, matching §8 condition 6"
        held = section["held_out_direct_outcomes_by_status"]
        assert set(held) == set(COHORT_STATUSES)
        below = [s for s in COHORT_STATUSES if held[s] < ADMISSIBILITY_FLOOR]
        assert below == section["statuses_below_floor"]
        assert section["admissible"] is (not below)

    def test_the_reductions_are_monotone_per_status(self) -> None:
        # canonical >= direct >= held-out, for every status. A violation means
        # the join fanned out, which the unique constraint on (player, game)
        # forbids within a store but cannot police across two.
        section = _load(ADMISSIBILITY)["section_2_admissibility"]
        canonical = section["canonical_observations_by_status"]
        direct = section["direct_outcomes_by_status"]
        held = section["held_out_direct_outcomes_by_status"]
        for status in COHORT_STATUSES:
            assert canonical[status] >= direct[status] >= held[status]

    def test_the_by_date_table_reconciles_with_the_direct_totals(self) -> None:
        artifact = _load(ADMISSIBILITY)
        by_date = artifact["direct_outcome_counts_by_game_date"]
        direct = artifact["section_2_admissibility"]["direct_outcomes_by_status"]
        for status in COHORT_STATUSES:
            assert sum(day.get(status, 0) for day in by_date.values()) == direct[status]

    def test_the_by_date_table_settles_the_split_without_regeneration(self) -> None:
        # The point of publishing by date: any chronological split is checkable
        # from the artifact alone, so moving the split needs no new ingest.
        artifact = _load(ADMISSIBILITY)
        by_date = artifact["direct_outcome_counts_by_game_date"]
        section = artifact["section_2_admissibility"]
        _dev, _sel, hold = chronological_split([date.fromisoformat(d) for d in by_date])
        recomputed = {
            s: sum(by_date[d.isoformat()].get(s, 0) for d in hold) for s in COHORT_STATUSES
        }
        assert recomputed == section["held_out_direct_outcomes_by_status"]
        assert len(hold) == section["split_game_dates"]["held_out"]

    def test_the_band_table_reconciles_with_the_direct_totals(self) -> None:
        artifact = _load(ADMISSIBILITY)
        bands = artifact["direct_outcomes_by_lead_time_band"]
        direct = artifact["section_2_admissibility"]["direct_outcomes_by_status"]
        for status in COHORT_STATUSES:
            assert sum(b.get(status, 0) for b in bands.values()) == direct[status]

    def test_the_join_is_declared_cross_store_on_stable_keys(self) -> None:
        join = _load(ADMISSIBILITY)["join"]
        assert join["is_cross_store"] is True
        assert join["local_surrogate_keys_are_not_used"] is True
        assert join["join_key"] == [
            "nba_games.nba_game_id",
            "player_external_ids[source=nba].external_id",
        ]

    def test_the_split_denominator_is_game_dates_not_calendar_days(self) -> None:
        artifact = _load(ADMISSIBILITY)
        scope = artifact["scope"]
        by_date = artifact["direct_outcome_counts_by_game_date"]
        span = (
            date.fromisoformat(scope["end_game_date"])
            - date.fromisoformat(scope["start_game_date"])
        ).days + 1
        assert scope["game_dates"] == len(by_date)
        assert scope["game_dates"] < span, "game dates must be distinct game dates, not days"
