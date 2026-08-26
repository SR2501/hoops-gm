"""Tests for post-parse projection verification.

Every check in ``verification.py`` is asserted twice: once that it stays quiet
on input that does not carry its defect, and once that it fires on input that
does. The second half is the one that matters. A check exercised only against
clean input has been shown to return "fine" and nothing more — it has not been
shown to be *capable* of returning anything else, and four false zeros in a
single day elsewhere in this project came from exactly that habit.

Two of these tests exist to pin honesty rather than behaviour:
``test_the_scoring_identity_cannot_detect_a_scale_error`` and
``test_an_absent_cohort_is_not_a_pass`` both assert that a check does *not* do
something it might be assumed to do.
"""

from __future__ import annotations

import string

import pytest

from hoops_gm.ingest.projections import (
    HASHTAG_PROFILE,
    ProjectionSourceRow,
    VerificationOutcome,
    parse_projection_csv,
    verify_no_baked_in_availability,
    verify_projection_batch,
    verify_scoring_identity,
    verify_value_shape,
)
from hoops_gm.ingest.projections.verification import (
    MIN_COHORT_FOR_BAKED_IN_CHECK,
    normalized_key,
)

# Distinct alphabetic names. Digits are stripped by the name normalizer, so
# "Player1"/"Player2" collapse to one key and silently produce a cohort of
# one — which is how the first draft of these tests produced an empty cohort
# that looked like a clean result.
_NAMES = [
    f"{first}{second}ovic Playerson{first}{second}"
    for first in string.ascii_uppercase[:10]
    for second in string.ascii_lowercase[:10]
]


def _row(name: str, **kwargs: float | None) -> ProjectionSourceRow:
    return ProjectionSourceRow(row_number=1, player_name=name, **kwargs)  # type: ignore[arg-type]


def _per_game_rows() -> list[ProjectionSourceRow]:
    return [
        _row(
            "Player Alpha",
            minutes_per_game=35.1,
            points_per_game=28.4,
            field_goals_made_per_game=10.5,
            three_pointers_made_per_game=1.8,
            free_throws_made_per_game=5.6,
            assumed_games_played=72,
        ),
        _row(
            "Player Beta",
            minutes_per_game=30.4,
            points_per_game=25.7,
            field_goals_made_per_game=9.2,
            three_pointers_made_per_game=2.2,
            free_throws_made_per_game=5.1,
            assumed_games_played=66,
        ),
    ]


def _scaled(rows: list[ProjectionSourceRow], factor: float) -> list[ProjectionSourceRow]:
    """The same rows as season totals — minutes deliberately left per-game.

    Hashtag's season-total mode leaves MPG per-game while scaling the counting
    stats, measured on the live page (35.1 in both modes, 28.4 -> 2042.6).
    Reproducing that asymmetry matters: a scaled fixture that also scaled
    minutes would let a minutes-based check appear to work.
    """
    return [
        _row(
            row.player_name,
            minutes_per_game=row.minutes_per_game,
            points_per_game=(row.points_per_game or 0) * factor,
            field_goals_made_per_game=(row.field_goals_made_per_game or 0) * factor,
            three_pointers_made_per_game=(row.three_pointers_made_per_game or 0) * factor,
            free_throws_made_per_game=(row.free_throws_made_per_game or 0) * factor,
            assumed_games_played=row.assumed_games_played,
        )
        for row in rows
    ]


class TestValueShape:
    def test_per_game_rates_pass(self) -> None:
        finding = verify_value_shape(_per_game_rows())
        assert finding.outcome is VerificationOutcome.PASSED

    def test_season_totals_are_caught(self) -> None:
        finding = verify_value_shape(_scaled(_per_game_rows(), 72))
        assert finding.outcome is VerificationOutcome.FAILED
        assert "season totals" in finding.detail

    def test_minutes_would_not_have_caught_it(self) -> None:
        """Why the discriminator is a counting stat, pinned as a test.

        The obvious check is "nobody plays more than 48 minutes". It is dead:
        Hashtag leaves minutes per-game in season-total mode, so the bound
        holds on both shapes and separates nothing. Asserting that here stops
        it being reintroduced as an apparently-sensible addition.
        """
        totals = _scaled(_per_game_rows(), 72)
        assert all((row.minutes_per_game or 0) <= 48 for row in totals)
        assert verify_value_shape(totals).outcome is VerificationOutcome.FAILED

    def test_empty_input_does_not_pass(self) -> None:
        finding = verify_value_shape([])
        assert finding.outcome is VerificationOutcome.NOT_RUN

    def test_the_false_pass_reading_is_carried_in_the_data(self) -> None:
        """A cohort of only low-volume players defeats this check, as documented.

        Constructed rather than described, because a false-pass reading that
        has never been executed is a claim, not a demonstration.
        """
        fringe = [
            _row(f"Fringe Player{letter}", points_per_game=0.8 * 40)
            for letter in string.ascii_uppercase[:10]
        ]
        assert all((row.points_per_game or 0) < 60 for row in fringe)
        assert verify_value_shape(fringe).outcome is VerificationOutcome.PASSED
        assert "low-volume" in verify_value_shape(fringe).false_pass_reading


class TestScoringIdentity:
    def test_consistent_rows_pass(self) -> None:
        assert verify_scoring_identity(_per_game_rows()).outcome is VerificationOutcome.PASSED

    def test_shifted_shooting_volume_is_caught(self) -> None:
        rows = _per_game_rows()
        broken = _row(
            "Player Gamma",
            points_per_game=28.4,
            field_goals_made_per_game=6.0,  # belongs to a different player
            three_pointers_made_per_game=1.8,
            free_throws_made_per_game=5.6,
        )
        finding = verify_scoring_identity([*rows, broken])
        assert finding.outcome is VerificationOutcome.FAILED
        assert "Player Gamma" in finding.detail

    def test_the_scoring_identity_cannot_detect_a_scale_error(self) -> None:
        """The honesty test. This check is algebraically scale-invariant.

        Multiply every scoring column by 72 and ``2*FGM + 3PM + FTM == PTS``
        still holds, so the identity passes cleanly while the season-totals
        defect is fully present. It is the strongest-looking check in the
        module and it is the wrong one for the job it looks suited to.

        Asserted rather than only documented, so that anyone tempted to
        promote it into the shape check has to delete a passing test to do so.
        """
        totals = _scaled(_per_game_rows(), 72)
        assert verify_scoring_identity(totals).outcome is VerificationOutcome.PASSED
        assert verify_value_shape(totals).outcome is VerificationOutcome.FAILED

    def test_rows_missing_a_component_do_not_pass_vacuously(self) -> None:
        partial = [_row("Player Alpha", points_per_game=28.4)]
        assert verify_scoring_identity(partial).outcome is VerificationOutcome.NOT_RUN


class TestBakedInAvailability:
    @staticmethod
    def _cohort(
        ratio: float, *, count: int = 40, games: float = 70
    ) -> tuple[list[ProjectionSourceRow], dict[str, float]]:
        rows = [
            _row(_NAMES[index], assumed_games_played=games, minutes_per_game=30.0 * ratio)
            for index in range(count)
        ]
        observed = {normalized_key(row): 30.0 for row in rows}
        assert len(observed) == count, "test names must not collide after normalization"
        return rows, observed

    def test_undiscounted_rates_pass(self) -> None:
        rows, observed = self._cohort(1.0)
        report = verify_no_baked_in_availability(rows, observed)
        assert report.finding.outcome is VerificationOutcome.PASSED
        assert report.median_ratio == pytest.approx(1.0)

    def test_pre_discounted_rates_are_caught(self) -> None:
        rows, observed = self._cohort(0.85)
        report = verify_no_baked_in_availability(rows, observed)
        assert report.finding.outcome is VerificationOutcome.FAILED
        assert "ADR-002" in report.finding.detail

    def test_direction_is_stated_so_the_opposite_is_not_a_failure(self) -> None:
        """A cohort projected for *more* minutes is not this defect.

        Without a stated direction the check would become "the ratio is near
        one", which fires on a source that is merely optimistic. That is a
        different finding and not one this check is entitled to make.
        """
        rows, observed = self._cohort(1.15)
        assert verify_no_baked_in_availability(rows, observed).finding.outcome is (
            VerificationOutcome.PASSED
        )

    def test_an_absent_cohort_is_not_a_pass(self) -> None:
        rows, observed = self._cohort(0.85, count=MIN_COHORT_FOR_BAKED_IN_CHECK - 1)
        report = verify_no_baked_in_availability(rows, observed)
        assert report.finding.outcome is VerificationOutcome.NOT_RUN
        assert "not a pass" in report.finding.detail.lower()

    def test_low_games_players_are_excluded_not_silently_counted(self) -> None:
        rows, observed = self._cohort(0.85, games=10)
        report = verify_no_baked_in_availability(rows, observed)
        assert report.cohort_size == 0
        assert report.finding.outcome is VerificationOutcome.NOT_RUN

    def test_it_is_never_a_per_row_gate(self) -> None:
        """One player losing his role must not fail the batch.

        A per-row version of this check would fire on every player whose
        minutes legitimately dropped — a trade, an ageing curve, a rookie
        drafted ahead of him — and would be wrong every time.
        """
        rows, observed = self._cohort(1.0)
        observed[normalized_key(rows[0])] = 60.0  # projected at half his old role
        report = verify_no_baked_in_availability(rows, observed)
        assert report.finding.outcome is VerificationOutcome.PASSED


class TestBatchReport:
    def test_the_fixture_passes_every_check_it_can_run(self) -> None:
        from pathlib import Path

        fixture = (
            Path(__file__).parent / "fixtures" / "projections" / "hashtag_sample.csv"
        ).read_text(encoding="utf-8")
        parsed = parse_projection_csv(fixture, HASHTAG_PROFILE, season="2026-27")

        report = verify_projection_batch(HASHTAG_PROFILE.profile_id, parsed.rows)
        assert report.passed
        assert {finding.check for finding in report.findings} == {
            "value_shape",
            "scoring_identity",
            "baked_in_availability",
        }

    def test_a_missing_input_records_not_run_rather_than_being_omitted(self) -> None:
        """An absent check and a passing check must not look the same.

        ``passed`` is True here, and the availability question is entirely
        unanswered. That is why ``passed`` is not the whole report and why the
        NOT_RUN finding is present rather than skipped.
        """
        report = verify_projection_batch("hashtag-2026-27", _per_game_rows())
        availability = next(
            finding for finding in report.findings if finding.check == "baked_in_availability"
        )
        assert availability.outcome is VerificationOutcome.NOT_RUN
        assert report.passed is True
        assert "unknown, not clean" in availability.detail
