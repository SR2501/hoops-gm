"""Structural draft-format contracts derived from ``League`` facts only."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest

from hoops_gm.db.models.enums import DraftType
from hoops_gm.db.models.league import League
from hoops_gm.draft.formats import (
    AuctionDraftFormat,
    DraftFormatError,
    DraftPick,
    LinearDraftFormat,
    RoundDirection,
    SnakeDraftFormat,
    draft_format_from_league,
)


def _league(
    *,
    draft_type: DraftType,
    team_count: int | None = 10,
    roster_size: int | None = 14,
    auction_budget: Decimal | None = None,
) -> League:
    return League(
        name="Test League",
        season="2026-27",
        draft_type=draft_type,
        team_count=team_count,
        roster_size=roster_size,
        auction_budget=auction_budget,
    )


@pytest.mark.parametrize(
    ("draft_type", "expected_type"),
    [
        (DraftType.SNAKE, SnakeDraftFormat),
        (DraftType.LINEAR, LinearDraftFormat),
    ],
)
def test_ordered_format_identity_and_shape(
    draft_type: DraftType,
    expected_type: type[SnakeDraftFormat] | type[LinearDraftFormat],
) -> None:
    result = draft_format_from_league(_league(draft_type=draft_type))

    assert type(result) is expected_type
    assert result.draft_type is draft_type
    assert result.team_count == 10
    assert result.roster_size == 14
    assert result.total_roster_slots == 140


def test_auction_format_requires_and_preserves_explicit_budget() -> None:
    result = draft_format_from_league(
        _league(
            draft_type=DraftType.AUCTION,
            team_count=12,
            roster_size=13,
            auction_budget=Decimal("250.00"),
        )
    )

    assert result == AuctionDraftFormat(
        team_count=12,
        roster_size=13,
        auction_budget=Decimal("250.00"),
    )
    assert result.draft_type is DraftType.AUCTION
    assert result.total_roster_slots == 156


@pytest.mark.parametrize("team_count", [None, 0, -1, cast(int, True)])
def test_missing_or_nonpositive_team_count_fails_closed(team_count: int | None) -> None:
    with pytest.raises(DraftFormatError, match="team_count"):
        draft_format_from_league(_league(draft_type=DraftType.SNAKE, team_count=team_count))


@pytest.mark.parametrize("roster_size", [None, 0, -1, cast(int, False)])
def test_missing_or_nonpositive_roster_size_fails_closed(roster_size: int | None) -> None:
    with pytest.raises(DraftFormatError, match="roster_size"):
        draft_format_from_league(_league(draft_type=DraftType.LINEAR, roster_size=roster_size))


def test_unknown_draft_type_fails_without_historical_defaults() -> None:
    with pytest.raises(DraftFormatError, match="unknown"):
        draft_format_from_league(
            _league(
                draft_type=DraftType.UNKNOWN,
                team_count=None,
                roster_size=None,
                auction_budget=None,
            )
        )


@pytest.mark.parametrize("raw_draft_type", ["snake", None, object()])
def test_untyped_draft_discriminator_fails_closed(raw_draft_type: object) -> None:
    league = _league(draft_type=DraftType.SNAKE)
    league.draft_type = cast(DraftType, raw_draft_type)

    with pytest.raises(DraftFormatError, match="DraftType"):
        draft_format_from_league(league)


@pytest.mark.parametrize("draft_type", [DraftType.SNAKE, DraftType.LINEAR])
def test_ordered_draft_rejects_inconsistent_auction_budget(draft_type: DraftType) -> None:
    with pytest.raises(DraftFormatError, match="must be absent"):
        draft_format_from_league(
            _league(
                draft_type=draft_type,
                auction_budget=Decimal("200.00"),
            )
        )


@pytest.mark.parametrize(
    "auction_budget",
    [
        None,
        Decimal("0"),
        Decimal("-0.01"),
        Decimal("NaN"),
        Decimal("Infinity"),
        cast(Decimal, 200),
    ],
)
def test_auction_rejects_missing_or_invalid_budget(
    auction_budget: Decimal | None,
) -> None:
    with pytest.raises(DraftFormatError, match="auction_budget"):
        draft_format_from_league(
            _league(
                draft_type=DraftType.AUCTION,
                auction_budget=auction_budget,
            )
        )


def test_snake_reverses_team_slots_on_even_rounds() -> None:
    draft = SnakeDraftFormat(team_count=4, roster_size=3)

    assert [draft.pick_at(pick).team_slot for pick in range(1, 13)] == [
        1,
        2,
        3,
        4,
        4,
        3,
        2,
        1,
        1,
        2,
        3,
        4,
    ]
    assert draft.round_direction(1) is RoundDirection.FORWARD
    assert draft.round_direction(2) is RoundDirection.REVERSE
    assert draft.pick_for(2, 1) == DraftPick(5, 2, 1, 4)
    assert draft.pick_for(2, 4) == DraftPick(8, 2, 4, 1)


def test_linear_preserves_team_slot_order_every_round() -> None:
    draft = LinearDraftFormat(team_count=4, roster_size=3)

    assert [draft.pick_at(pick).team_slot for pick in range(1, 13)] == [
        1,
        2,
        3,
        4,
        1,
        2,
        3,
        4,
        1,
        2,
        3,
        4,
    ]
    assert all(
        draft.round_direction(round_number) is RoundDirection.FORWARD
        for round_number in range(1, 4)
    )
    assert draft.pick_for(2, 1) == DraftPick(5, 2, 1, 1)
    assert draft.pick_for(2, 4) == DraftPick(8, 2, 4, 4)


@pytest.mark.parametrize("team_count", [1, 2, 3, 10, 12])
@pytest.mark.parametrize("roster_size", [1, 2, 14])
def test_ordered_formats_form_a_complete_bijection(
    team_count: int,
    roster_size: int,
) -> None:
    for draft in (
        SnakeDraftFormat(team_count=team_count, roster_size=roster_size),
        LinearDraftFormat(team_count=team_count, roster_size=roster_size),
    ):
        picks = [draft.pick_at(overall) for overall in range(1, draft.total_roster_slots + 1)]
        assert [pick.overall_pick for pick in picks] == list(range(1, draft.total_roster_slots + 1))
        for round_number in range(1, roster_size + 1):
            round_picks = [pick for pick in picks if pick.round_number == round_number]
            assert [pick.pick_in_round for pick in round_picks] == list(range(1, team_count + 1))
            assert sorted(pick.team_slot for pick in round_picks) == list(range(1, team_count + 1))


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("pick_at", (0,)),
        ("pick_at", (7,)),
        ("pick_at", (cast(int, True),)),
        ("pick_for", (0, 1)),
        ("pick_for", (3, 1)),
        ("pick_for", (1, 0)),
        ("pick_for", (1, 4)),
    ],
)
def test_ordered_pick_coordinates_are_bounded(
    method: str,
    args: tuple[int, ...],
) -> None:
    draft = SnakeDraftFormat(team_count=3, roster_size=2)

    with pytest.raises(DraftFormatError):
        getattr(draft, method)(*args)


def test_formats_and_picks_have_deterministic_value_equality() -> None:
    first = SnakeDraftFormat(team_count=10, roster_size=14)
    second = SnakeDraftFormat(team_count=10, roster_size=14)

    assert first == second
    assert first.pick_at(20) == second.pick_at(20)
