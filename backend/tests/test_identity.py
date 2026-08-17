"""Risk R7: the player identity crosswalk gets its own test suite.

A silent mismatch here corrupts every downstream number and looks like a
modelling bug for weeks. There is no shared identifier between the sources —
verified live, see ``docs/adapters/`` — so every match is inferred, and the
things that make an inference auditable (per-field evidence, a recorded method,
a manual-override flag, an unmatched report) are the actual product.

Several of these tests encode failures found by running the resolver against
the real 2026-08-17 payloads rather than by reasoning about it.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

import pytest

from hoops_gm.db.models.enums import FieldEvidence
from hoops_gm.identity import (
    IdentityResolver,
    MatchEvidence,
    ResolutionReport,
    ResolvableRecord,
    compare_optional,
    compare_positions,
    normalize_key,
    normalize_name,
    normalize_positions,
    normalize_team_abbreviation,
    partition,
    render_summary,
    score_evidence,
    to_csv,
)
from hoops_gm.identity.report import REVIEW_COLUMNS
from hoops_gm.ingest.fantrax_official import parse_player_ids
from hoops_gm.ingest.nba import parse_common_all_players

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ==========================================================================
# Name normalisation
# ==========================================================================


class TestNameNormalisation:
    @pytest.mark.parametrize(
        ("left", "right"),
        [
            # The two orderings both sources use.
            ("Jokic, Nikola", "Nikola Jokic"),
            ("Antetokounmpo, Giannis", "Giannis Antetokounmpo"),
            # Diacritics: sources disagree per endpoint, not just per source.
            ("Jokić, Nikola", "Jokic, Nikola"),
            ("Dončić, Luka", "Doncic, Luka"),
            ("Šengün, Alperen", "Sengun, Alperen"),
            ("Schröder, Dennis", "Schroder, Dennis"),
            # Punctuation.
            ("O'Neal, Shaquille", "Oneal, Shaquille"),
            ("Towns, Karl-Anthony", "Karl Anthony Towns"),
            ("Alexander-Walker, Nickeil", "Nickeil Alexander Walker"),
            # Suffixes are held apart from the key.
            ("Jackson Jr., Jaren", "Jaren Jackson"),
            ("Pippen Jr., Scotty", "Scotty Pippen"),
            ("Holmes II, DaRon", "DaRon Holmes"),
            # A suffix between two commas. Real, from CommonAllPlayers, and it
            # produced the key "jr ernest udeh" until it was handled.
            ("Udeh, Jr., Ernest", "Ernest Udeh"),
        ],
    )
    def test_equivalent_spellings_produce_the_same_key(self, left: str, right: str) -> None:
        assert normalize_key(left) == normalize_key(right)

    def test_different_people_do_not_collide(self) -> None:
        assert normalize_key("Johnson, Jalen") != normalize_key("Johnson, Jaden")
        assert normalize_key("Jackson, Justin") != normalize_key("Jackson, Jaren")

    def test_the_suffix_is_kept_separately_rather_than_discarded(self) -> None:
        """Discarding it merges father and son; keeping it in the key blocks a
        match whenever one source omits it. Neither is acceptable, so it lives
        beside the key."""
        senior = normalize_name("Gary Payton")
        junior = normalize_name("Gary Payton II")
        assert senior.key == junior.key
        assert senior.suffix == ""
        assert junior.suffix == "ii"
        assert senior.key_with_suffix != junior.key_with_suffix

    def test_a_lone_suffix_like_token_is_treated_as_a_name(self) -> None:
        """ "V" alone is a name fragment, not a generational suffix."""
        parsed = normalize_name("V")
        assert parsed.key == "v"
        assert parsed.suffix == ""

    def test_the_raw_string_is_always_preserved(self) -> None:
        parsed = normalize_name("Jokić, Nikola")
        assert parsed.raw == "Jokić, Nikola"

    def test_an_empty_name_normalises_without_raising(self) -> None:
        parsed = normalize_name("")
        assert parsed.key == ""
        assert parsed.raw == ""


class TestTeamNormalisation:
    @pytest.mark.parametrize(
        ("fantrax", "nba"),
        [
            ("NO", "NOP"),
            ("NY", "NYK"),
            ("SA", "SAS"),
            ("GS", "GSW"),
            ("PHO", "PHX"),
            ("UTAH", "UTA"),
        ],
    )
    def test_the_six_franchises_the_sources_spell_differently(self, fantrax: str, nba: str) -> None:
        """A fifth of the league. Left unmapped, the team component of a match
        disagrees for six franchises and scores correct matches down."""
        assert normalize_team_abbreviation(fantrax) == normalize_team_abbreviation(nba)

    @pytest.mark.parametrize("absent", ["(N/A)", "N/A", "", "  ", "FA", "TOT", None])
    def test_absent_team_markers_normalise_to_empty(self, absent: str | None) -> None:
        """Empty means *unknown*, which the resolver must treat as absence of
        evidence rather than as evidence of disagreement."""
        assert normalize_team_abbreviation(absent) == ""


class TestPositionNormalisation:
    def test_coarse_positions_are_comparable_across_granularities(self) -> None:
        assert normalize_positions("PG") == normalize_positions("G")
        assert normalize_positions("SF") == normalize_positions("F")
        assert normalize_positions("PG/SG") == frozenset({"G"})
        assert normalize_positions("SF,PF") == frozenset({"F"})

    def test_an_unrecognised_label_yields_no_positions(self) -> None:
        assert normalize_positions("Default") == frozenset()
        assert normalize_positions("Tm") == frozenset()


# ==========================================================================
# Evidence
# ==========================================================================


class TestFieldEvidence:
    def test_absence_is_unknown_not_agreement_and_not_disagreement(self) -> None:
        assert compare_optional(None, "LAL") is FieldEvidence.UNKNOWN
        assert compare_optional("", "LAL") is FieldEvidence.UNKNOWN
        assert compare_optional("LAL", "LAL") is FieldEvidence.AGREE
        assert compare_optional("LAL", "BOS") is FieldEvidence.DISAGREE

    def test_positions_agree_when_they_overlap_rather_than_match_exactly(self) -> None:
        assert compare_positions("PG", "G") is FieldEvidence.AGREE
        assert compare_positions("PG", "C") is FieldEvidence.DISAGREE
        assert compare_positions("PG", None) is FieldEvidence.UNKNOWN

    def test_a_name_disagreement_floors_the_score(self) -> None:
        """Nothing else can rescue a match between two different names."""
        evidence = MatchEvidence(
            name=FieldEvidence.DISAGREE,
            team=FieldEvidence.AGREE,
            position=FieldEvidence.AGREE,
            suffix=FieldEvidence.AGREE,
        )
        assert score_evidence(evidence) == 0.0

    def test_unknown_fields_neither_add_nor_subtract(self) -> None:
        name_only = MatchEvidence(name=FieldEvidence.AGREE)
        with_team = MatchEvidence(name=FieldEvidence.AGREE, team=FieldEvidence.AGREE)
        assert 0.0 < score_evidence(name_only) < score_evidence(with_team)

    def test_the_score_stays_inside_the_unit_interval(self) -> None:
        """``player_external_ids.confidence`` has a CHECK requiring [0, 1]."""
        everything = MatchEvidence(
            name=FieldEvidence.AGREE,
            team=FieldEvidence.AGREE,
            position=FieldEvidence.AGREE,
            suffix=FieldEvidence.AGREE,
        )
        assert 0.0 <= score_evidence(everything) <= 1.0
        contradicted = MatchEvidence(
            name=FieldEvidence.AGREE,
            team=FieldEvidence.DISAGREE,
            position=FieldEvidence.DISAGREE,
            suffix=FieldEvidence.DISAGREE,
        )
        assert 0.0 <= score_evidence(contradicted) <= 1.0

    def test_the_summary_names_which_fields_disagreed(self) -> None:
        evidence = MatchEvidence(
            name=FieldEvidence.AGREE,
            team=FieldEvidence.DISAGREE,
            position=FieldEvidence.UNKNOWN,
            suffix=FieldEvidence.UNKNOWN,
        )
        summary = evidence.summary()
        assert "DISAGREE: team" in summary
        assert evidence.disagreements == ("team",)
        assert set(evidence.unknowns) == {"position", "suffix"}


# ==========================================================================
# Resolution
# ==========================================================================


def record(
    key: str, name: str, team: str | None = None, position: str | None = None
) -> ResolvableRecord:
    return ResolvableRecord.build(key=key, name=name, team=team, position=position)


@functools.lru_cache(maxsize=1)
def _resolve_real_payloads() -> ResolutionReport:
    """Resolve the committed Fantrax and NBA payloads against each other.

    Cached rather than a class-scoped fixture: parsing 1,788 Fantrax rows and
    580 NBA rows for each of five assertions is wasteful, and a class-scoped
    fixture collides with the function-scoped autouse fixtures in ``conftest``.
    """
    fantrax = parse_player_ids(load("fantrax_getplayerids_nba.json"))
    nba = parse_common_all_players(load("nba_commonallplayers_current.json"))
    targets = [
        ResolvableRecord.build(key=p.fantrax_id, name=p.name, team=p.team, position=p.position)
        for p in fantrax.players
    ]
    sources = [
        ResolvableRecord.build(
            key=str(p.nba_player_id),
            name=p.display_last_comma_first,
            team=p.team_abbreviation,
        )
        for p in nba
    ]
    return IdentityResolver(targets).resolve(sources)


class TestResolution:
    def test_a_unique_exact_name_match_is_accepted(self) -> None:
        resolver = IdentityResolver([record("1", "Jokic, Nikola", "DEN")])
        resolution = resolver.resolve_one(record("a", "Nikola Jokić", "DEN"))
        assert resolution.accepted
        assert resolution.best is not None
        assert resolution.best.target.key == "1"

    def test_a_unique_name_with_no_corroboration_is_still_accepted(self) -> None:
        """Uniqueness is itself evidence, and it was being thrown away.

        ``CommonAllPlayers`` carries no position, so a Fantrax row could reach
        at most 0.90 — and only 0.70 whenever the NBA side had no current team.
        The first real run put 898 of 1,788 rows into manual review with the
        identical reason "name agrees, nothing else is known", which is a queue
        nobody reads honestly. Matching one name uniquely out of thousands is a
        strong argument on its own.
        """
        resolver = IdentityResolver([record("1", "Booth, Phil")])
        resolution = resolver.resolve_one(record("a", "Phil Booth"))
        assert resolution.accepted
        assert resolution.best is not None
        assert resolution.best.uniqueness_bonus > 0
        # The field-evidence score is recoverable, so the match is re-arguable.
        assert resolution.best.field_confidence < resolution.best.confidence

    def test_two_people_with_one_name_are_separated_by_team_not_rejected(self) -> None:
        """The real case: two "Johnson, Jalen" rows exist in Fantrax alone."""
        resolver = IdentityResolver(
            [record("1", "Johnson, Jalen", "ATL"), record("2", "Johnson, Jalen", "")]
        )
        resolution = resolver.resolve_one(record("a", "Jalen Johnson", "ATL"))
        assert resolution.accepted
        assert resolution.best is not None
        assert resolution.best.target.key == "1"
        assert resolution.runner_up is not None

    def test_two_indistinguishable_candidates_go_to_a_human(self) -> None:
        """Picking the higher of two near-identical scores silently is exactly
        how a season's numbers get corrupted."""
        resolver = IdentityResolver([record("1", "Johnson, Jalen"), record("2", "Johnson, Jalen")])
        resolution = resolver.resolve_one(record("a", "Jalen Johnson"))
        assert not resolution.accepted
        assert resolution.reason.startswith("ambiguous:")
        assert resolution.best is not None
        assert resolution.runner_up is not None

    def test_a_stale_team_snapshot_flags_for_review_rather_than_dropping(self) -> None:
        """Found by running it: Fantrax had Giannis on MIA (2026-27) while
        ``CommonAllPlayers`` for 2025-26 had him on MIL. A heavy team penalty
        pushed him — and Luguentz Dort, and Naz Reid — below the review floor
        and out as *no candidate at all*.

        Mid-season the same happens for days around any trade, whichever source
        updates second. So it must land in front of a human, not vanish.
        """
        resolver = IdentityResolver([record("1", "Antetokounmpo, Giannis", "MIL")])
        resolution = resolver.resolve_one(record("a", "Antetokounmpo, Giannis", "MIA"))
        assert not resolution.accepted, "a contradicted team should not auto-accept"
        assert resolution.best is not None, "nor should it disappear from the report"
        assert resolution.evidence.team is FieldEvidence.DISAGREE
        assert resolution.evidence.name is FieldEvidence.AGREE

    def test_an_abbreviated_given_name_matches(self) -> None:
        resolver = IdentityResolver([record("1", "Thomas, Cam", "BKN")])
        resolution = resolver.resolve_one(record("a", "Thomas, Cameron", "BKN"))
        assert resolution.best is not None
        assert resolution.evidence.name is FieldEvidence.AGREE

    def test_a_single_initial_does_not_match_everything(self) -> None:
        """Two characters is the shortest abbreviation worth honouring."""
        resolver = IdentityResolver([record("1", "Smith, J")])
        resolution = resolver.resolve_one(record("a", "Smith, Jordan"))
        assert not resolution.accepted

    def test_no_shared_name_yields_no_candidate(self) -> None:
        resolver = IdentityResolver([record("1", "Jokic, Nikola")])
        resolution = resolver.resolve_one(record("a", "Doncic, Luka"))
        assert not resolution.accepted
        assert resolution.best is None
        assert resolution.confidence == 0.0

    def test_two_source_records_may_not_both_claim_one_player(self) -> None:
        """The mirror of ambiguity, and the one that reaches the database.

        ``resolve_one`` asks "is this record ambiguous between candidates?" and
        cannot see the reverse: two source rows each being the confident best
        match for the same player. Found by running the importer, which hit
        ``uq_player_external_ids_current`` on two "Williams, Jaylin" rows
        resolving onto one NBA player. Without the demotion the crosswalk fans
        out and every aggregate through it double-counts.
        """
        resolver = IdentityResolver([record("nba1", "Williams, Jaylin", "OKC")])
        report = resolver.resolve(
            [
                record("fx1", "Williams, Jaylin", "OKC"),
                record("fx2", "Williams, Jaylin", "OKC"),
            ]
        )
        assert report.accepted == []
        assert len(report.needs_review) == 2
        for resolution in report.needs_review:
            assert resolution.reason.startswith("collision:")
            assert "Williams, Jaylin" in resolution.reason

    def test_a_collision_still_names_the_player_both_rows_claimed(self) -> None:
        resolver = IdentityResolver([record("nba1", "Johnson, Jalen", "ATL")])
        report = resolver.resolve(
            [record("fx1", "Johnson, Jalen", "ATL"), record("fx2", "Johnson, Jalen", "ATL")]
        )
        ambiguous, _, _ = partition(report)
        assert len(ambiguous) == 2

    def test_distinct_players_do_not_trigger_a_collision(self) -> None:
        resolver = IdentityResolver(
            [record("nba1", "Jokic, Nikola", "DEN"), record("nba2", "Doncic, Luka", "LAL")]
        )
        report = resolver.resolve(
            [record("fx1", "Nikola Jokic", "DEN"), record("fx2", "Luka Doncic", "LAL")]
        )
        assert len(report.accepted) == 2

    def test_the_recorded_method_never_claims_a_shared_identifier(self) -> None:
        """``anchor_id`` would be a lie: no shared key exists between these
        sources, which is the whole of risk R23."""
        resolver = IdentityResolver([record("1", "Jokic, Nikola", "DEN")])
        resolution = resolver.resolve_one(record("a", "Nikola Jokic", "DEN"))
        assert resolution.match_method != "anchor_id"
        assert resolution.match_method in {"normalized_name", "name_team_position", "fuzzy"}

    def test_confidence_is_always_storable(self) -> None:
        """``player_external_ids.confidence`` has a CHECK requiring [0, 1]."""
        resolver = IdentityResolver(
            [record("1", "Johnson, Jalen", "ATL"), record("2", "Johnson, Jalen", "BOS")]
        )
        for name in ("Jalen Johnson", "Nikola Jokic", "Johnson, Jalen"):
            resolution = resolver.resolve_one(record("a", name, "ATL"))
            assert 0.0 <= resolution.confidence <= 1.0


# ==========================================================================
# Against the real payloads
# ==========================================================================


class TestAgainstRealPayloads:
    @pytest.fixture
    def resolved(self) -> ResolutionReport:
        return _resolve_real_payloads()

    def test_almost_every_rostered_nba_player_finds_its_fantrax_row(
        self, resolved: ResolutionReport
    ) -> None:
        """The direction that matters operationally: these are the players the
        league can actually draft.

        The threshold is a regression guard, not a target. It was 98.6% when
        written; a drop means either the payloads diverged or the resolver got
        worse, and both need a person.
        """
        assert resolved.total > 400
        assert resolved.match_rate > 0.95, render_summary(resolved)

    def test_no_match_is_ever_silently_ambiguous(self, resolved: ResolutionReport) -> None:
        ambiguous, _, _ = partition(resolved)
        for resolution in ambiguous:
            assert resolution.best is not None
            assert resolution.runner_up is not None
            assert not resolution.accepted

    def test_every_accepted_match_agrees_on_the_name(self, resolved: ResolutionReport) -> None:
        for resolution in resolved.accepted:
            assert resolution.evidence.name is FieldEvidence.AGREE

    def test_no_accepted_match_contradicts_on_any_field(self, resolved: ResolutionReport) -> None:
        """A disagreement anywhere should cost enough to require a human."""
        for resolution in resolved.accepted:
            assert resolution.evidence.disagreements == (), (
                f"{resolution.source_record.raw_name!r} was accepted despite "
                f"{resolution.evidence.summary()}"
            )

    def test_no_two_accepted_matches_claim_the_same_player(
        self, resolved: ResolutionReport
    ) -> None:
        """The constraint ``uq_player_external_ids_current`` enforces this at
        the database. It must not be reached — a crosswalk that fans out makes
        every aggregate through it double-count."""
        targets = [r.best.target.key for r in resolved.accepted if r.best]
        assert len(targets) == len(set(targets))

    def test_every_unresolved_record_carries_a_reason_a_human_can_act_on(
        self, resolved: ResolutionReport
    ) -> None:
        for resolution in [*resolved.needs_review, *resolved.unmatched]:
            assert resolution.reason
            assert len(resolution.reason) > 20

    def test_team_entities_never_reach_the_resolver_as_players(self) -> None:
        """R24 again, from the other end: a franchise row must not be matchable."""
        fantrax = parse_player_ids(load("fantrax_getplayerids_nba.json"))
        keys = {p.fantrax_id for p in fantrax.players}
        assert not [k for k in keys if "#" in k]


# ==========================================================================
# The unmatched report
# ==========================================================================


class TestUnmatchedReport:
    @pytest.fixture
    def report(self) -> ResolutionReport:
        resolver = IdentityResolver(
            [
                record("1", "Johnson, Jalen"),
                record("2", "Johnson, Jalen"),
                record("3", "Jokic, Nikola", "DEN"),
                record("4", "Antetokounmpo, Giannis", "MIL"),
            ]
        )
        return resolver.resolve(
            [
                record("a", "Jalen Johnson"),
                record("b", "Nikola Jokic", "DEN"),
                record("c", "Antetokounmpo, Giannis", "MIA"),
                record("d", "Doncic, Luka", "LAL"),
            ]
        )

    def test_the_three_groups_need_three_different_actions(self, report: ResolutionReport) -> None:
        ambiguous, low_confidence, no_candidate = partition(report)
        assert len(ambiguous) == 1
        assert len(low_confidence) == 1
        assert len(no_candidate) == 1
        assert len(report.accepted) == 1

    def test_the_csv_carries_the_evidence_a_human_needs(self, report: ResolutionReport) -> None:
        ambiguous, low_confidence, no_candidate = partition(report)
        rendered = to_csv([*ambiguous, *low_confidence, *no_candidate])
        header, *rows = rendered.strip().splitlines()
        assert header == ",".join(REVIEW_COLUMNS)
        assert len(rows) == 3
        # Per-field evidence, not just a number: the point of the whole design.
        for column in ("name_evidence", "team_evidence", "position_evidence", "suffix_evidence"):
            assert column in header

    def test_the_decision_columns_are_left_blank_for_a_human(
        self, report: ResolutionReport
    ) -> None:
        """Blank means "not yet looked at", which is different from a decision
        to reject — so it is not defaulted."""
        ambiguous, _, _ = partition(report)
        rendered = to_csv(ambiguous)
        assert rendered.strip().splitlines()[1].endswith(",,")

    def test_the_summary_leads_with_the_ambiguous_group(self, report: ResolutionReport) -> None:
        summary = render_summary(report, source_label="test")
        assert "ambiguous" in summary
        assert "accepted automatically" in summary
