"""Stats: NBA games and the box-score rows attached to them.

**Makes and attempts are stored; percentages are not.** FG% and FT% are ratio
categories whose fantasy impact depends on volume — a 90% free-throw shooter on
one attempt is worthless. Storing a percentage throws away the denominator and
makes the volume-weighted calculation impossible to do correctly later. This is
risk R9, and the schema is the first place to prevent it.

Minutes are stored as whole seconds. Upstream gives ``"34:12"``; a float of
minutes loses information and invites floating-point comparisons in aggregation.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, UTCDateTime, portable_enum
from hoops_gm.db.models.enums import GameStatus, SeasonType, StatScope

if TYPE_CHECKING:
    from hoops_gm.db.models.identity import NbaTeam, Player
    from hoops_gm.db.models.schedule import TeamScheduleEntry


class BoxScoreMixin:
    """Raw counting columns shared by per-game and per-season rows.

    Nullable throughout: a player who did not appear has no box score, and
    zero is a different claim from absent. Availability modelling depends on
    that distinction, so the schema must not flatten it.
    """

    seconds_played: Mapped[int | None] = mapped_column()

    field_goals_made: Mapped[int | None] = mapped_column()
    field_goals_attempted: Mapped[int | None] = mapped_column()
    three_pointers_made: Mapped[int | None] = mapped_column()
    three_pointers_attempted: Mapped[int | None] = mapped_column()
    free_throws_made: Mapped[int | None] = mapped_column()
    free_throws_attempted: Mapped[int | None] = mapped_column()

    points: Mapped[int | None] = mapped_column()
    offensive_rebounds: Mapped[int | None] = mapped_column()
    defensive_rebounds: Mapped[int | None] = mapped_column()
    rebounds: Mapped[int | None] = mapped_column()
    assists: Mapped[int | None] = mapped_column()
    steals: Mapped[int | None] = mapped_column()
    blocks: Mapped[int | None] = mapped_column()
    turnovers: Mapped[int | None] = mapped_column()
    personal_fouls: Mapped[int | None] = mapped_column()
    plus_minus: Mapped[int | None] = mapped_column()


#: The vocabulary a ratio scoring category may name as its numerator or
#: denominator. Written out rather than derived from ``BoxScoreMixin`` at
#: import time, because these values end up inside a CHECK constraint in a
#: migration and a constraint whose contents shift with a refactor is worse
#: than one that is explicit. ``test_schema.py`` asserts it stays in step with
#: the mixin.
BOX_SCORE_STAT_KEYS: Final[tuple[str, ...]] = (
    "assists",
    "blocks",
    "defensive_rebounds",
    "field_goals_attempted",
    "field_goals_made",
    "free_throws_attempted",
    "free_throws_made",
    "offensive_rebounds",
    "personal_fouls",
    "plus_minus",
    "points",
    "rebounds",
    "seconds_played",
    "steals",
    "three_pointers_attempted",
    "three_pointers_made",
    "turnovers",
)


def stat_key_sql_list() -> str:
    """The stat vocabulary as a SQL ``IN`` list, for CHECK constraints."""
    return ", ".join(f"'{key}'" for key in BOX_SCORE_STAT_KEYS)


class NbaGame(IntPk, TimestampMixin, Base):
    """A single NBA game."""

    __tablename__ = "nba_games"
    __table_args__ = (
        Index("ix_nba_games_season_date", "season", "game_date"),
        CheckConstraint("home_team_id <> away_team_id", name="distinct_teams"),
    )

    #: NBA season in ``2026-27`` form. String, not integer, because a season
    #: spans two calendar years and every upstream renders it this way.
    season: Mapped[str] = mapped_column(String(9), index=True)
    season_type: Mapped[SeasonType] = mapped_column(
        portable_enum(SeasonType, "season_type"), default=SeasonType.REGULAR
    )
    nba_game_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    game_date: Mapped[date] = mapped_column(Date, index=True)
    #: Tip-off as a UTC instant. Local date and instant are both needed:
    #: fantasy days are defined in local time, back-to-back and rest-day
    #: detection need the instant. ``UTCDateTime`` rather than
    #: ``DateTime(timezone=True)`` because SQLite silently discards the offset
    #: from the latter, and this column feeds the availability model.
    tipoff_utc: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[GameStatus] = mapped_column(
        portable_enum(GameStatus, "game_status"), default=GameStatus.SCHEDULED
    )

    home_team_id: Mapped[int] = mapped_column(ForeignKey("nba_teams.id"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("nba_teams.id"), index=True)
    home_score: Mapped[int | None] = mapped_column()
    away_score: Mapped[int | None] = mapped_column()

    home_team: Mapped[NbaTeam] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[NbaTeam] = relationship(foreign_keys=[away_team_id])
    player_logs: Mapped[list[PlayerGameLog]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    schedule_entries: Mapped[list[TeamScheduleEntry]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<NbaGame {self.nba_game_id} {self.game_date}>"


class PlayerGameLog(BoxScoreMixin, IntPk, TimestampMixin, Base):
    """One player's box score for one game.

    Only rows for players who actually appeared. Absence is not recorded here —
    it belongs in ``player_participation``, which the availability engine owns
    in Phase 4. Keeping the two apart is what stops "no row" from silently
    meaning "zero production".
    """

    __tablename__ = "player_game_logs"
    __table_args__ = (
        UniqueConstraint("player_id", "game_id", name="uq_player_game_logs_player_game"),
        Index("ix_player_game_logs_game_team", "game_id", "team_id"),
    )

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("nba_games.id", ondelete="CASCADE"), index=True)
    #: The team the player appeared for in this game, which is not necessarily
    #: ``players.current_team_id``.
    team_id: Mapped[int] = mapped_column(ForeignKey("nba_teams.id"), index=True)
    started: Mapped[bool | None] = mapped_column()

    player: Mapped[Player] = relationship(back_populates="game_logs")
    game: Mapped[NbaGame] = relationship(back_populates="player_logs")
    team: Mapped[NbaTeam] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PlayerGameLog player={self.player_id} game={self.game_id}>"


class PlayerSeasonStat(BoxScoreMixin, IntPk, TimestampMixin, Base):
    """Season aggregate for one player.

    A traded player has one row per team plus a combined row. Distinguishing
    them cannot be done with a nullable ``team_id`` in the unique key: SQL
    treats NULLs as distinct on both SQLite and Postgres, so two season totals
    for the same player would both be accepted. ``team_key`` is therefore a
    non-null discriminator — a team abbreviation, or ``TOT`` for the combined
    row — and it is what the unique constraint uses. ``team_id`` remains as the
    foreign key to join on.

    Totals, not averages. Per-game rates are derived, and deriving them from
    totals is exact; storing rounded averages is not reversible.
    """

    __tablename__ = "player_season_stats"
    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "season",
            "season_type",
            "team_key",
            name="uq_player_season_stats_identity",
        ),
        CheckConstraint(
            "(scope = 'team' AND team_id IS NOT NULL AND team_key <> 'TOT') "
            "OR (scope = 'total' AND team_id IS NULL AND team_key = 'TOT')",
            name="scope_team_consistency",
        ),
        Index("ix_player_season_stats_season_scope", "season", "scope"),
    )

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    season: Mapped[str] = mapped_column(String(9), index=True)
    season_type: Mapped[SeasonType] = mapped_column(
        portable_enum(SeasonType, "season_type"), default=SeasonType.REGULAR
    )
    scope: Mapped[StatScope] = mapped_column(
        portable_enum(StatScope, "stat_scope"), default=StatScope.TOTAL
    )
    #: Team abbreviation, or ``TOT`` for the season-total row. Non-null so it
    #: can carry the uniqueness that a nullable foreign key cannot.
    team_key: Mapped[str] = mapped_column(String(8), default="TOT")
    team_id: Mapped[int | None] = mapped_column(ForeignKey("nba_teams.id"), index=True)

    games_played: Mapped[int | None] = mapped_column()
    games_started: Mapped[int | None] = mapped_column()
    #: Games the player's team played while they were on the roster. Games
    #: played divided by this is an availability rate; without it, games played
    #: alone cannot distinguish injury from a mid-season trade.
    team_games: Mapped[int | None] = mapped_column()

    player: Mapped[Player] = relationship(back_populates="season_stats")
    team: Mapped[NbaTeam | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PlayerSeasonStat player={self.player_id} {self.season} {self.scope}>"
