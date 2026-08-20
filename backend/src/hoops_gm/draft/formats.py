"""Typed structural contracts for supported draft formats.

The league row is the only input. No historical league defaults, market
evidence, valuation, or auction strategy enters this layer. Ordered drafts
expose only their one-indexed pick order; auctions expose only the per-team
budget stated by the league because nomination and bidding order are not
represented by the current league facts.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from hoops_gm.db.models.enums import DraftType
from hoops_gm.db.models.league import League


class DraftFormatError(ValueError):
    """The league facts cannot form a supported, internally consistent draft."""


class RoundDirection(enum.StrEnum):
    """The team-slot traversal used by one ordered-draft round."""

    FORWARD = "forward"
    REVERSE = "reverse"


@dataclass(frozen=True, slots=True)
class DraftPick:
    """One selection in an ordered draft, using one-indexed coordinates."""

    overall_pick: int
    round_number: int
    pick_in_round: int
    team_slot: int


def _positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise DraftFormatError(f"{field_name} must be a positive integer, got {value!r}")
    return value


def _validate_shape(team_count: object, roster_size: object) -> None:
    _positive_int(team_count, field_name="team_count")
    _positive_int(roster_size, field_name="roster_size")


def _bounded_int(value: object, *, field_name: str, upper_bound: int) -> int:
    parsed = _positive_int(value, field_name=field_name)
    if parsed > upper_bound:
        raise DraftFormatError(f"{field_name} must be at most {upper_bound}, got {parsed}")
    return parsed


def _ordered_pick(
    *,
    team_count: int,
    roster_size: int,
    round_number: object,
    pick_in_round: object,
    direction: RoundDirection,
) -> DraftPick:
    round_value = _bounded_int(
        round_number,
        field_name="round_number",
        upper_bound=roster_size,
    )
    pick_value = _bounded_int(
        pick_in_round,
        field_name="pick_in_round",
        upper_bound=team_count,
    )
    team_slot = pick_value if direction is RoundDirection.FORWARD else team_count - pick_value + 1
    return DraftPick(
        overall_pick=(round_value - 1) * team_count + pick_value,
        round_number=round_value,
        pick_in_round=pick_value,
        team_slot=team_slot,
    )


def _coordinates_for_overall_pick(
    overall_pick: object,
    *,
    team_count: int,
    total_roster_slots: int,
) -> tuple[int, int]:
    overall_value = _bounded_int(
        overall_pick,
        field_name="overall_pick",
        upper_bound=total_roster_slots,
    )
    round_index, pick_index = divmod(overall_value - 1, team_count)
    return round_index + 1, pick_index + 1


@dataclass(frozen=True, slots=True)
class SnakeDraftFormat:
    """A draft whose team-slot order reverses after every round."""

    team_count: int
    roster_size: int
    draft_type: Literal[DraftType.SNAKE] = field(
        default=DraftType.SNAKE,
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_shape(self.team_count, self.roster_size)

    @property
    def total_roster_slots(self) -> int:
        return self.team_count * self.roster_size

    def round_direction(self, round_number: int) -> RoundDirection:
        round_value = _bounded_int(
            round_number,
            field_name="round_number",
            upper_bound=self.roster_size,
        )
        if round_value % 2:
            return RoundDirection.FORWARD
        return RoundDirection.REVERSE

    def pick_for(self, round_number: int, pick_in_round: int) -> DraftPick:
        return _ordered_pick(
            team_count=self.team_count,
            roster_size=self.roster_size,
            round_number=round_number,
            pick_in_round=pick_in_round,
            direction=self.round_direction(round_number),
        )

    def pick_at(self, overall_pick: int) -> DraftPick:
        round_number, pick_in_round = _coordinates_for_overall_pick(
            overall_pick,
            team_count=self.team_count,
            total_roster_slots=self.total_roster_slots,
        )
        return self.pick_for(round_number, pick_in_round)


@dataclass(frozen=True, slots=True)
class LinearDraftFormat:
    """A draft whose team-slot order is identical in every round."""

    team_count: int
    roster_size: int
    draft_type: Literal[DraftType.LINEAR] = field(
        default=DraftType.LINEAR,
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_shape(self.team_count, self.roster_size)

    @property
    def total_roster_slots(self) -> int:
        return self.team_count * self.roster_size

    def round_direction(self, round_number: int) -> RoundDirection:
        _bounded_int(
            round_number,
            field_name="round_number",
            upper_bound=self.roster_size,
        )
        return RoundDirection.FORWARD

    def pick_for(self, round_number: int, pick_in_round: int) -> DraftPick:
        return _ordered_pick(
            team_count=self.team_count,
            roster_size=self.roster_size,
            round_number=round_number,
            pick_in_round=pick_in_round,
            direction=self.round_direction(round_number),
        )

    def pick_at(self, overall_pick: int) -> DraftPick:
        round_number, pick_in_round = _coordinates_for_overall_pick(
            overall_pick,
            team_count=self.team_count,
            total_roster_slots=self.total_roster_slots,
        )
        return self.pick_for(round_number, pick_in_round)


@dataclass(frozen=True, slots=True)
class AuctionDraftFormat:
    """An auction's roster shape and explicit per-team budget."""

    team_count: int
    roster_size: int
    auction_budget: Decimal
    draft_type: Literal[DraftType.AUCTION] = field(
        default=DraftType.AUCTION,
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_shape(self.team_count, self.roster_size)
        if (
            not isinstance(self.auction_budget, Decimal)
            or not self.auction_budget.is_finite()
            or self.auction_budget <= 0
        ):
            raise DraftFormatError(
                f"auction_budget must be a positive finite Decimal, got {self.auction_budget!r}"
            )

    @property
    def total_roster_slots(self) -> int:
        return self.team_count * self.roster_size


type DraftFormat = SnakeDraftFormat | LinearDraftFormat | AuctionDraftFormat


def draft_format_from_league(league: League) -> DraftFormat:
    """Build a format from the four explicit draft facts on ``league``.

    ``UNKNOWN`` and raw/untyped discriminators fail closed. Auction budget is
    required only for auctions and forbidden for ordered drafts, so stale or
    contradictory configuration cannot silently cross this seam.
    """

    draft_type = league.draft_type
    if not isinstance(draft_type, DraftType):
        raise DraftFormatError(f"draft_type must be a DraftType, got {draft_type!r}")

    if draft_type is DraftType.UNKNOWN:
        raise DraftFormatError("draft_type is unknown")

    team_count = _positive_int(league.team_count, field_name="team_count")
    roster_size = _positive_int(league.roster_size, field_name="roster_size")

    if draft_type is DraftType.AUCTION:
        auction_budget = league.auction_budget
        if auction_budget is None:
            raise DraftFormatError("auction_budget is required for auction drafts")
        return AuctionDraftFormat(
            team_count=team_count,
            roster_size=roster_size,
            auction_budget=auction_budget,
        )

    if league.auction_budget is not None:
        raise DraftFormatError(f"auction_budget must be absent for {draft_type.value} drafts")

    if draft_type is DraftType.SNAKE:
        return SnakeDraftFormat(team_count=team_count, roster_size=roster_size)
    if draft_type is DraftType.LINEAR:
        return LinearDraftFormat(team_count=team_count, roster_size=roster_size)

    raise DraftFormatError(f"unsupported draft_type: {draft_type!r}")
