"""Identity: canonical players, their cross-source identifiers, and NBA teams.

Player identity is the highest-risk item in the project (risk R7). Fantrax
identifiers, NBA identifiers and projection-CSV name strings all disagree, and
getting a match wrong silently corrupts every number downstream of it.

Phase 1 builds the tables, not the resolver. The shape below is what the
resolver needs to exist without a rewrite:

* one canonical ``players`` row per human being, with a surrogate key that
  belongs to nobody upstream;
* many ``player_external_ids`` rows, each scoped to a source, each carrying the
  raw name string as it appeared at that source, a confidence score and the
  method that produced it;
* a manual override flag that the resolver is required to treat as final, so a
  human correction survives the next re-run.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, portable_enum
from hoops_gm.db.models.enums import (
    Conference,
    ExternalSource,
    MatchMethod,
    PlayerStatus,
)

if TYPE_CHECKING:
    from hoops_gm.db.models.stats import PlayerGameLog, PlayerSeasonStat


class NbaTeam(IntPk, TimestampMixin, Base):
    """An NBA franchise."""

    __tablename__ = "nba_teams"

    nba_team_id: Mapped[int] = mapped_column(unique=True, index=True)
    abbreviation: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    city: Mapped[str | None] = mapped_column(String(64))
    conference: Mapped[Conference | None] = mapped_column(portable_enum(Conference, "conference"))
    division: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(default=True)

    players: Mapped[list[Player]] = relationship(back_populates="current_team")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<NbaTeam {self.abbreviation}>"


class Player(IntPk, TimestampMixin, Base):
    """A canonical player.

    The primary key is ours. No upstream identifier is promoted to a key,
    because doing so would make one source's opinion of identity structural.
    """

    __tablename__ = "players"

    full_name: Mapped[str] = mapped_column(String(128), index=True)
    #: Case-, punctuation- and suffix-stripped name used as a matching key.
    #: Populated by the Phase 2 resolver; not unique, because "Marcus Williams"
    #: happens more than once and collisions must be resolvable, not rejected.
    normalized_name: Mapped[str] = mapped_column(String(128), index=True)
    first_name: Mapped[str | None] = mapped_column(String(64))
    last_name: Mapped[str | None] = mapped_column(String(64))
    birth_date: Mapped[date | None] = mapped_column(Date)
    height_inches: Mapped[int | None] = mapped_column()
    weight_pounds: Mapped[int | None] = mapped_column()
    #: NBA's own positional label. League-specific eligibility is a Fantrax
    #: concept and belongs to the league tables, not here.
    primary_position: Mapped[str | None] = mapped_column(String(16))
    rookie_season: Mapped[str | None] = mapped_column(String(9))
    status: Mapped[PlayerStatus] = mapped_column(
        portable_enum(PlayerStatus, "player_status"), default=PlayerStatus.UNKNOWN
    )
    current_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("nba_teams.id", ondelete="SET NULL"), index=True
    )

    current_team: Mapped[NbaTeam | None] = relationship(back_populates="players")
    external_ids: Mapped[list[PlayerExternalId]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )
    game_logs: Mapped[list[PlayerGameLog]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )
    season_stats: Mapped[list[PlayerSeasonStat]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Player {self.id} {self.full_name!r}>"


class PlayerExternalId(IntPk, TimestampMixin, Base):
    """One source's identifier for a canonical player.

    ``(source, external_id)`` is unique: a single upstream identifier may not
    point at two people. The reverse is not constrained — a player legitimately
    has one row per source, and more than one row for a source that changed its
    identifier between seasons is a real situation the resolver must be able to
    represent.

    ``confidence`` and ``match_method`` exist so that the unmatched/low-
    confidence report required by Phase 2 is a query, not a re-derivation.
    ``is_manual_override`` is the resolver's stop sign: a human decision must
    survive the next automated pass.
    """

    __tablename__ = "player_external_ids"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_player_external_ids_source_ext"),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="confidence_range",
        ),
        Index("ix_player_external_ids_player_source", "player_id", "source"),
        Index("ix_player_external_ids_source_norm_name", "source", "normalized_name"),
    )

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    source: Mapped[ExternalSource] = mapped_column(portable_enum(ExternalSource, "external_source"))
    #: Optional finer scoping within a source — a specific CSV import batch, or
    #: a league id where the source namespaces identifiers per league.
    source_detail: Mapped[str | None] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(64))
    #: The name exactly as the source wrote it. Projection CSVs have no
    #: identifier at all, so the raw string *is* the evidence for the match and
    #: has to be retrievable when a match is later disputed.
    external_name: Mapped[str | None] = mapped_column(String(128))
    normalized_name: Mapped[str | None] = mapped_column(String(128))
    external_team: Mapped[str | None] = mapped_column(String(16))
    external_position: Mapped[str | None] = mapped_column(String(16))

    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    match_method: Mapped[MatchMethod] = mapped_column(
        portable_enum(MatchMethod, "match_method"), default=MatchMethod.ANCHOR_ID
    )
    is_manual_override: Mapped[bool] = mapped_column(default=False, index=True)
    #: Set when a human has looked at this row, whether or not they changed it.
    reviewed_at: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    player: Mapped[Player] = relationship(back_populates="external_ids")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PlayerExternalId {self.source}:{self.external_id} -> {self.player_id}>"
