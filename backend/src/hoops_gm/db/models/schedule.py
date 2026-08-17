"""Schedule: the per-team view of the season calendar.

``team_schedule`` is a deliberate, documented denormalisation — two rows per
game, one per team. ``nba_games`` is the canonical record; this is the shape
that rest, density, road-trip and off-night questions are actually asked in,
and answering them by self-joining ``nba_games`` on both team columns is the
kind of query that is easy to get subtly wrong under time pressure.

**What is deliberately not here, and why.**

The plan's Schedule group also lists ``schedule_density``, ``off_night_slates``
and ``opponent_context``. Those are not built in Phase 1. Their columns are not
ingest facts — they are modelling choices (which density windows matter, what
counts as a light slate, how category defence is expressed) owned by ``quant``
and ``data-engineer`` in Phase 3. Fixing that shape now, before anyone has
tried to compute it, is precisely the "painted into a corner" outcome Phase 1
is supposed to avoid. Everything they need to attach to is here: a stable
per-team, per-game row with a surrogate key.

``week_definitions`` is also absent, but for a different reason: it and
``scoring_periods`` describe the same thing. A fantasy week *is* a scoring
period, and a league's periods are the ones that decide matchups. Two tables
that must agree and have no mechanism to enforce agreement is a bug waiting to
happen, so there is one — ``league.ScoringPeriod``. If a league-independent
NBA week calendar is ever needed for streaming analysis, it should be added
then, on evidence.

Both departures are recorded in ``docs/handoff.md``.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, portable_enum
from hoops_gm.db.models.enums import SeasonType

if TYPE_CHECKING:
    from hoops_gm.db.models.identity import NbaTeam
    from hoops_gm.db.models.stats import NbaGame


class TeamScheduleEntry(IntPk, TimestampMixin, Base):
    """One team's fixture in one game."""

    __tablename__ = "team_schedule"
    __table_args__ = (
        UniqueConstraint("game_id", "team_id", name="uq_team_schedule_game_team"),
        CheckConstraint("team_id <> opponent_team_id", name="distinct_schedule_teams"),
        Index("ix_team_schedule_team_date", "team_id", "game_date"),
        Index("ix_team_schedule_season_date", "season", "game_date"),
    )

    season: Mapped[str] = mapped_column(String(9), index=True)
    season_type: Mapped[SeasonType] = mapped_column(
        portable_enum(SeasonType, "season_type"), default=SeasonType.REGULAR
    )
    game_id: Mapped[int] = mapped_column(ForeignKey("nba_games.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("nba_teams.id"), index=True)
    opponent_team_id: Mapped[int] = mapped_column(ForeignKey("nba_teams.id"), index=True)
    #: Denormalised from ``nba_games`` so a season's fixtures for one team is a
    #: single indexed scan. Kept in step by the ingest that writes both.
    game_date: Mapped[date] = mapped_column(Date, index=True)
    is_home: Mapped[bool] = mapped_column()

    game: Mapped[NbaGame] = relationship(back_populates="schedule_entries")
    team: Mapped[NbaTeam] = relationship(foreign_keys=[team_id])
    opponent: Mapped[NbaTeam] = relationship(foreign_keys=[opponent_team_id])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<TeamScheduleEntry team={self.team_id} game={self.game_id}>"
