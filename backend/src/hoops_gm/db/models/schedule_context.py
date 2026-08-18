"""Quant-owned schedule context used to condition p(play) and reliability.

This is intentionally not a schedule fact table. The raw calendar is owned by
``team_schedule`` and any pure calendar arithmetic stays in ``schedule_density``.
The context here is modelling output: pace, category defence, blowout risk and
light-slate identification.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Date, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, UTCDateTime

if TYPE_CHECKING:
    from hoops_gm.db.models.identity import NbaTeam
    from hoops_gm.db.models.schedule import TeamScheduleEntry


class OpponentContext(IntPk, TimestampMixin, Base):
    """Per-team fixture environment for a game."""

    __tablename__ = "opponent_context"
    __table_args__ = (
        UniqueConstraint(
            "team_schedule_id",
            "model_version",
            "schedule_version",
            name="uq_opponent_context_schedule_version",
        ),
        Index("ix_opponent_context_game_date", "game_date"),
        Index("ix_opponent_context_team_schedule", "team_schedule_id"),
        Index("ix_opponent_context_team_date", "team_id", "game_date"),
        Index("ix_opponent_context_model_version", "model_version"),
        Index("ix_opponent_context_schedule_version", "schedule_version"),
    )

    season: Mapped[str] = mapped_column(String(9))
    game_date: Mapped[date] = mapped_column(Date)
    team_schedule_id: Mapped[int] = mapped_column(
        ForeignKey("team_schedule.id", ondelete="CASCADE")
    )
    team_id: Mapped[int] = mapped_column(ForeignKey("nba_teams.id"))
    opponent_team_id: Mapped[int] = mapped_column(ForeignKey("nba_teams.id"))
    is_home: Mapped[bool] = mapped_column()
    pace_possessions: Mapped[float] = mapped_column()
    pace_window_games: Mapped[int] = mapped_column()
    category_defence: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    defence_window_games: Mapped[int] = mapped_column()
    blowout_probability: Mapped[float] = mapped_column()
    garbage_time_suppression: Mapped[float] = mapped_column()
    training_cutoff: Mapped[date | None] = mapped_column(Date, nullable=True)
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    model_version: Mapped[str] = mapped_column(String(64))
    schedule_version: Mapped[str] = mapped_column(String(64))
    schedule_refreshed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    team_schedule: Mapped[TeamScheduleEntry] = relationship()
    team: Mapped[NbaTeam] = relationship(foreign_keys=[team_id])
    opponent: Mapped[NbaTeam] = relationship(foreign_keys=[opponent_team_id])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<OpponentContext team={self.team_id} game_date={self.game_date}>"


class OffNightSlate(IntPk, TimestampMixin, Base):
    """Date-level light-slate context used for streaming and lineup decisions."""

    __tablename__ = "off_night_slates"
    __table_args__ = (
        UniqueConstraint(
            "slate_date",
            "model_version",
            "schedule_version",
            name="uq_off_night_slates_date_version",
        ),
        Index("ix_off_night_slates_model_version", "model_version"),
        Index("ix_off_night_slates_slate_date", "slate_date"),
        Index("ix_off_night_slates_schedule_version", "schedule_version"),
    )

    season: Mapped[str] = mapped_column(String(9))
    slate_date: Mapped[date] = mapped_column(Date)
    scheduled_game_count: Mapped[int] = mapped_column()
    scheduled_team_count: Mapped[int] = mapped_column()
    is_off_night: Mapped[bool] = mapped_column()
    light_slate_percentile: Mapped[float | None] = mapped_column(nullable=True)
    threshold_games: Mapped[int | None] = mapped_column(nullable=True)
    threshold_percentile: Mapped[float | None] = mapped_column(nullable=True)
    streaming_window_score: Mapped[float | None] = mapped_column(nullable=True)
    model_version: Mapped[str] = mapped_column(String(64))
    schedule_version: Mapped[str] = mapped_column(String(64))
    schedule_refreshed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<OffNightSlate date={self.slate_date} off_night={self.is_off_night}>"
