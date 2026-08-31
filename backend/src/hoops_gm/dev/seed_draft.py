"""Seed a local database with two recorded mock drafts, end to end.

**Every selection, seat and price here is invented.** Standalone player names
are invented too. The composed demo may instead supply canonical names from its
synthetic projection cohort so the category screen can exercise its identity
join, but that still records no draft that happened. A screenshot proves
*shape* and nothing else — not a real room's pace, not a real price distribution,
not what a real nomination order looks like. The seeded drafts say so in their
own ``notes`` field, so a reader who finds this database without finding this
file still learns it from the data.

**Why this exists.** ``GET /api/v1/drafts`` has never returned a non-empty body
outside pytest, and a screen is about to be built against it. The same gap the
schedule grid and the projections endpoint were both in before their seeds:
an endpoint that answers correctly and answers *nothing*, where "it works"
and "it has never worked" are indistinguishable from the outside.

**It drives the real service functions, not the ORM.** Every event below goes
through :mod:`hoops_gm.draft.service`, so if derivation refuses an event the
seed fails rather than writing a log the API could not have produced. A seed
that inserted rows directly would happily create a state no recorder could
reach, and the screen would then be built against a shape that cannot occur.

Two drafts, because the format abstraction covers both and the owner made the
point himself that snake mocks still carry co-selection, handcuffs, positional
runs and ADP-versus-behaviour divergence:

* an **auction** mock, the format his league actually uses, exercising a
  nomination/bid/sale cycle, a standalone sale with no nomination (the fast
  path a live room actually produces), and a correction recorded as a ``void``;
* a **snake** mock, exercising the serpentine order and ``next_pick``.

Usage::

    python -m hoops_gm.dev.seed_draft --database-url sqlite:///./draft_demo.db

**This writes to our own database and nowhere else.** No Fantrax call, no
queued action, no transport. It is not the automation write path.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hoops_gm.core.config import Settings
from hoops_gm.db.models.draft import Draft
from hoops_gm.db.models.enums import DraftToolUsage, DraftType, ScoringType
from hoops_gm.db.models.league import League
from hoops_gm.db.session import Database
from hoops_gm.dev.seed_schedule_grid import (
    SEASON,
    DemoSeedRefused,
    create_schema_only_on_a_fresh_database,
    redacted_url,
)
from hoops_gm.draft import service
from hoops_gm.draft.state import DraftStateView

#: Marks every league and draft this seed creates. The refusal below keys on
#: it, so a database holding the owner's own recorded mock is never touched.
DEMO_PREFIX = "[demo] "

#: Fixed so two runs against two fresh databases produce identical rows.
SEEDED_AT = datetime(2026, 8, 21, 19, 30, tzinfo=UTC)

DEMO_NOTE = (
    "Synthetic. Every seat, price and selection in this draft is invented. "
    "Player labels may be canonical synthetic-demo cohort names; no part of "
    "this records a draft that happened."
)

AUCTION_TEAMS = 12
AUCTION_ROSTER = 13
AUCTION_BUDGET = Decimal("200.00")

SNAKE_TEAMS = 10
SNAKE_ROSTER = 13

_AUCTION_SEATS = (
    "Bench Mob",
    "Rim Protectors",
    "Free Throw Merchants",
    "Turnover Chain",
    "Load Management",
    "Small Ball Five",
    "Corner Threes",
    "Second Unit",
    "Trade Deadline",
    "Two Way Contract",
    "Buyout Market",
    "Garbage Time",
)

_SNAKE_SEATS = _AUCTION_SEATS[:SNAKE_TEAMS]

#: Standalone labels. Deliberately not real NBA names: a demo database sitting
#: next to real captures should not read as one. ``seed_demo`` replaces them
#: through the typed optional input; the standalone command leaves ``player_id``
#: NULL, exactly the state a mock on an un-ingested site produces.
_AUCTION_LOTS = (
    ("Ansel Whitcombe", 1, Decimal("62.00")),
    ("Dov Kestrel", 4, Decimal("48.00")),
    ("Ilario Bexley", 7, Decimal("41.00")),
    ("Marek Sandoval-Quist", 2, Decimal("35.00")),
    ("Teodor Fane", 11, Decimal("29.00")),
    ("Oskar Vellamo", 5, Decimal("22.00")),
)

_AUCTION_CORRECTION_LOT = ("Cassian Ferro", 10, Decimal("18.00"))

_SNAKE_PICKS = (
    "Ansel Whitcombe",
    "Dov Kestrel",
    "Ilario Bexley",
    "Marek Sandoval-Quist",
    "Teodor Fane",
    "Oskar Vellamo",
    "Cassian Ferro",
    "Rune Halvorsen",
    "Émile Baptiste",
    "Wren Achterberg",
    "Bodhi Ngata",
    "Solomon Reyes-Okafor",
)


@dataclass(frozen=True, slots=True)
class CanonicalDraftPlayer:
    """A canonical player the composed demo may record instead of an invented name."""

    player_id: int
    player_label: str


@dataclass(frozen=True)
class DraftSeedResult:
    """What the seed put in the database, for the caller to assert against."""

    auction_league_id: int
    auction_draft_id: int
    auction_last_sequence: int
    auction_selections: int
    snake_league_id: int
    snake_draft_id: int
    snake_last_sequence: int
    snake_selections: int


def require_no_recorded_draft(session: Session) -> None:
    """Refuse a database holding any draft this seed did not create.

    Keyed on the name prefix rather than on emptiness, so re-running the seed
    against its own output is fine and running it against the database holding
    a mock the owner actually recorded is not. Losing a recorded draft is not
    recoverable: the log *is* the evidence, and there is no second copy.
    """

    names = session.scalars(select(Draft.name)).all()
    foreign = [name for name in names if not name.startswith(DEMO_PREFIX)]
    if foreign:
        raise DemoSeedRefused(
            f"this database holds {len(foreign)} draft(s) this seed did not create "
            f"({foreign[0]!r}); point --database-url at a scratch database"
        )


def _demo_league(session: Session, *, name: str, fmt: DraftType, budget: Decimal | None) -> League:
    """One local league per configuration.

    ``fantrax_league_id`` stays ``NULL``, which is what that column is nullable
    for (``league.py``): a mock configuration exists locally without being a
    Fantrax league, so a 12-team $200 mock against strangers gets its own row
    rather than being crammed into the real league's numbers.
    """

    full_name = f"{DEMO_PREFIX}{name}"
    existing = session.scalars(select(League).where(League.name == full_name)).first()
    if existing is not None:
        return existing
    league = League(
        fantrax_league_id=None,
        name=full_name,
        season=SEASON,
        scoring_type=ScoringType.H2H_CATEGORIES,
        draft_type=fmt,
        team_count=AUCTION_TEAMS if fmt is DraftType.AUCTION else SNAKE_TEAMS,
        roster_size=AUCTION_ROSTER if fmt is DraftType.AUCTION else SNAKE_ROSTER,
        auction_budget=budget,
        is_active=False,
    )
    session.add(league)
    session.flush()
    return league


def _seats(names: tuple[str, ...]) -> list[service.ParticipantSpec]:
    return [
        service.ParticipantSpec(
            team_slot=index,
            display_name=name,
            # Seat 1 is the owner's. Exactly one, which the schema enforces.
            is_owner=index == 1,
        )
        for index, name in enumerate(names, start=1)
    ]


def seed_auction_draft(
    session: Session,
    *,
    selection_players: Sequence[CanonicalDraftPlayer] | None = None,
) -> tuple[League, Draft, DraftStateView]:
    """A recorded auction mock, driven through the real recorders.

    ``None`` preserves the standalone seed's invented, unresolved names. The
    composed seed passes canonical players from its synthetic projection import;
    only those supplied are selected, so a short cohort cannot be padded with
    names that would make its category-table join partial without saying so.
    """
    league = _demo_league(
        session, name="Auction mock league", fmt=DraftType.AUCTION, budget=AUCTION_BUDGET
    )
    draft = service.create_draft(
        session,
        league=league,
        name=f"{DEMO_PREFIX}Auction mock, 12-team $200",
        tool_usage=DraftToolUsage.BLIND,
        is_mock=True,
        notes=DEMO_NOTE,
        participants=_seats(_AUCTION_SEATS),
    )
    seats = {seat.team_slot: seat.id for seat in draft.participants}

    plans = (*_AUCTION_LOTS, _AUCTION_CORRECTION_LOT)
    seeded_lots: list[tuple[str, int | None, int, Decimal]]
    if selection_players is None:
        seeded_lots = [
            (player_label, None, winning_slot, price) for player_label, winning_slot, price in plans
        ]
    else:
        seeded_lots = [
            (player.player_label, player.player_id, winning_slot, price)
            for player, (_, winning_slot, price) in zip(selection_players, plans, strict=False)
        ]

    state = service.load_state(session, draft)
    for index, (player_label, player_id, winning_slot, price) in enumerate(
        seeded_lots[: len(_AUCTION_LOTS)]
    ):
        nominator = seats[(index % AUCTION_TEAMS) + 1]
        winner = seats[winning_slot]
        if index == 0:
            # A full cycle: nomination, an intermediate bid from somebody who
            # loses, then the sale. This is what the recorder catches when the
            # room is slow enough to type into.
            state = service.record_nomination(
                session,
                draft,
                participant_id=nominator,
                player_label=player_label,
                player_id=player_id,
                opening_bid=Decimal("1.00"),
                occurred_at=SEEDED_AT,
            )
            state = service.record_bid(
                session, draft, participant_id=seats[3], amount=price - Decimal("5.00")
            )
            state = service.record_sale(
                session,
                draft,
                participant_id=winner,
                amount=price,
                player_label=player_label,
                player_id=player_id,
            )
            continue
        if index == 1:
            # The fast path: the sale is all the recorder caught. Refusing this
            # would lose the only fact worth having about the lot.
            state = service.record_sale(
                session,
                draft,
                participant_id=winner,
                amount=price,
                player_label=player_label,
                player_id=player_id,
                note="sale only; nomination went past too fast to type",
            )
            continue
        state = service.record_nomination(
            session,
            draft,
            participant_id=nominator,
            player_label=player_label,
            player_id=player_id,
        )
        if player_id is None:
            state = service.record_sale(session, draft, participant_id=winner, amount=price)
        else:
            state = service.record_sale(
                session,
                draft,
                participant_id=winner,
                amount=price,
                player_label=player_label,
                player_id=player_id,
            )

    # A correction, recorded the only way this unit allows: appended, never
    # applied. The mistaken sale stays in the log and stops counting.
    if len(seeded_lots) > len(_AUCTION_LOTS):
        player_label, player_id, winning_slot, price = seeded_lots[len(_AUCTION_LOTS)]
        mistake = service.record_sale(
            session,
            draft,
            participant_id=seats[9],
            amount=price,
            player_label=player_label,
            player_id=player_id,
            note=f"misheard; it was seat {winning_slot}",
        )
        state = service.record_void(
            session,
            draft,
            supersedes_sequence=mistake.last_sequence,
            note="wrong seat",
        )
        state = service.record_sale(
            session,
            draft,
            participant_id=seats[winning_slot],
            amount=price,
            player_label=player_label,
            player_id=player_id,
        )
    return league, draft, state


def seed_snake_draft(session: Session) -> tuple[League, Draft, DraftStateView]:
    """A recorded snake mock, so the ordered path has data too."""
    league = _demo_league(session, name="Snake mock league", fmt=DraftType.SNAKE, budget=None)
    draft = service.create_draft(
        session,
        league=league,
        name=f"{DEMO_PREFIX}Snake mock, 10-team",
        tool_usage=DraftToolUsage.BLIND,
        is_mock=True,
        notes=DEMO_NOTE,
        participants=_seats(_SNAKE_SEATS),
    )
    state = service.load_state(session, draft)
    for player in _SNAKE_PICKS:
        # The seat is read from the derived state rather than computed here.
        # Recomputing serpentine order in a seed would be a second definition
        # of the draft order, and a seed that disagrees with the abstraction is
        # a seed that proves the wrong screen works.
        if state.next_pick_participant_id is None:
            raise DemoSeedRefused(
                f"the board has no seat due to pick after {state.selections_made} "
                f"selections; the demo pick list is longer than the board"
            )
        state = service.record_pick(
            session,
            draft,
            participant_id=state.next_pick_participant_id,
            player_label=player,
        )
    return league, draft, state


def seed_drafts(
    session: Session,
    *,
    auction_players: Sequence[CanonicalDraftPlayer] | None = None,
) -> DraftSeedResult:
    """Seed both formats; canonical auction players are opt-in for composition."""
    require_no_recorded_draft(session)
    auction_league, auction_draft, auction_state = seed_auction_draft(
        session, selection_players=auction_players
    )
    snake_league, snake_draft, snake_state = seed_snake_draft(session)
    return DraftSeedResult(
        auction_league_id=auction_league.id,
        auction_draft_id=auction_draft.id,
        auction_last_sequence=auction_state.last_sequence,
        auction_selections=auction_state.selections_made,
        snake_league_id=snake_league.id,
        snake_draft_id=snake_draft.id,
        snake_last_sequence=snake_state.last_sequence,
        snake_selections=snake_state.selections_made,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=None,
        help="Defaults to the configured DATABASE_URL.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI entry point
    args = _parse_args(argv)
    url = args.database_url or Settings(_env_file=None).database_url
    database = Database.from_settings(Settings(database_url=url, _env_file=None))
    try:
        create_schema_only_on_a_fresh_database(database)
        with database.session() as session:
            result = seed_drafts(session)
    except DemoSeedRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        traceback.print_exc()
        print("database error; nothing was seeded", file=sys.stderr)
        return 4
    finally:
        database.dispose()

    print(
        json.dumps(
            {
                "database_url": redacted_url(url),
                "auction_league_id": result.auction_league_id,
                "auction_draft_id": result.auction_draft_id,
                "auction_last_sequence": result.auction_last_sequence,
                "auction_selections": result.auction_selections,
                "snake_league_id": result.snake_league_id,
                "snake_draft_id": result.snake_draft_id,
                "snake_last_sequence": result.snake_last_sequence,
                "snake_selections": result.snake_selections,
            },
            indent=2,
        )
    )
    print(
        "\nEvery seat, name and price in these drafts is invented. Nothing here "
        "records a draft that happened, and a screenshot taken from it proves "
        "shape and nothing else.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
