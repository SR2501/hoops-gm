"""Availability: the observed participation ledger.

**This is the observed record only.** ``p(play)``, reliability metrics,
shutdown risk and contingent value are modelled quantities owned by `quant` in
Phase 4 and do not belong here. Ingest owns what a source said happened;
modelling owns what it means. Keeping them in separate tables is what stops a
model's output from later being mistaken for an observation.

Two properties of this table exist because of what the sources actually do.

**The raw comment is never dropped.** ``reason`` is a normalisation of
``raw_comment`` and the normalisation will be wrong at first — the vocabulary
is inconsistent between scorers and seasons, and "rest" is routinely laundered
as a minor ailment. Keeping the original text means a better normalisation can
be re-derived from history rather than only applied going forward.

**Absence of evidence is recorded as such.** ``inactive_list_available`` says
whether the source offered an inactive list for that game at all. Without it,
"nobody was inactive" and "this endpoint has stopped telling us" are the same
row — and they were, silently, for the whole of the 2025-26 season on
``BoxScoreSummaryV2``, which returned an empty list for every date after
opening night while ``BoxScoreSummaryV3`` returned the real ones.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, UTCDateTime, portable_enum
from hoops_gm.db.models.enums import (
    DnpReason,
    ExternalSource,
    ParticipationOutcome,
    SeasonType,
)

if TYPE_CHECKING:
    from hoops_gm.db.models.identity import NbaTeam, Player
    from hoops_gm.db.models.stats import NbaGame


class PlayerParticipation(IntPk, TimestampMixin, Base):
    """Whether one player took part in one game, and what was said about it.

    Distinct from ``player_game_logs``, which holds production for players who
    appeared. A player who did not appear has no box score but does have a
    participation row, and that asymmetry is deliberate: it is what stops "no
    row" from silently meaning "zero production".
    """

    __tablename__ = "player_participation"
    __table_args__ = (
        UniqueConstraint("player_id", "game_id", name="uq_player_participation_player_game"),
        Index("ix_player_participation_game_outcome", "game_id", "outcome"),
        Index("ix_player_participation_player_outcome", "player_id", "outcome"),
    )

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("nba_games.id", ondelete="CASCADE"), index=True)
    #: The team the player was with for this game, which is not necessarily
    #: ``players.current_team_id``.
    team_id: Mapped[int] = mapped_column(ForeignKey("nba_teams.id"), index=True)

    outcome: Mapped[ParticipationOutcome] = mapped_column(
        portable_enum(ParticipationOutcome, "participation_outcome")
    )
    reason: Mapped[DnpReason] = mapped_column(
        portable_enum(DnpReason, "dnp_reason"), default=DnpReason.NONE_GIVEN
    )
    #: Exactly the text the source gave, inconsistent spacing and all. Never
    #: normalised in place, never dropped.
    raw_comment: Mapped[str] = mapped_column(Text, default="")
    #: Present for a player who appeared; ``None`` for one who did not. Zero
    #: and absent are different claims and must stay different.
    seconds_played: Mapped[int | None] = mapped_column()

    source: Mapped[ExternalSource] = mapped_column(
        portable_enum(ExternalSource, "external_source"), default=ExternalSource.NBA
    )
    #: Whether the source offered an inactive list for this game at all. See
    #: the module docstring — this is the difference between "nobody" and
    #: "we no longer know".
    inactive_list_available: Mapped[bool] = mapped_column(default=False)

    player: Mapped[Player] = relationship()
    game: Mapped[NbaGame] = relationship()
    team: Mapped[NbaTeam] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PlayerParticipation player={self.player_id} game={self.game_id} {self.outcome}>"


class AbsenceSplit(IntPk, TimestampMixin, Base):
    """Descriptive teammate production evidence for games with/without a player.

    This is deliberately an observation-layer aggregate, not a causal estimate
    and not a recommendation. ``provenance`` retains every source row and the
    bounded membership observations that permitted an otherwise missing row to
    be classified as an absence.
    """

    __tablename__ = "absence_splits"
    __table_args__ = (
        UniqueConstraint(
            "beneficiary_player_id",
            "absent_player_id",
            "team_id",
            "season",
            "season_type",
            "evidence_version",
            "input_fingerprint",
            name="uq_absence_splits_pair_evidence",
        ),
        CheckConstraint(
            "beneficiary_player_id <> absent_player_id",
            name="distinct_players",
        ),
        CheckConstraint("games_with > 0", name="games_with_positive"),
        CheckConstraint("games_without > 0", name="games_without_positive"),
        CheckConstraint(
            "explicit_absence_games + inferred_absence_games = games_without",
            name="absence_provenance_counts_match",
        ),
        CheckConstraint("data_layer = 'observations'", name="observation_layer_only"),
        CheckConstraint("claim_type = 'descriptive'", name="descriptive_claim_only"),
        Index(
            "ix_absence_splits_absent_season",
            "absent_player_id",
            "season",
        ),
        Index(
            "ix_absence_splits_beneficiary_season",
            "beneficiary_player_id",
            "season",
        ),
        Index("ix_absence_splits_team_season", "team_id", "season"),
        Index("ix_absence_splits_evidence_version", "evidence_version"),
        Index("ix_absence_splits_schedule_version", "schedule_version"),
    )

    beneficiary_player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"))
    absent_player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"))
    team_id: Mapped[int] = mapped_column(ForeignKey("nba_teams.id"))
    season: Mapped[str] = mapped_column(String(9))
    season_type: Mapped[SeasonType] = mapped_column(portable_enum(SeasonType, "season_type"))

    games_with: Mapped[int] = mapped_column()
    games_without: Mapped[int] = mapped_column()
    explicit_absence_games: Mapped[int] = mapped_column()
    inferred_absence_games: Mapped[int] = mapped_column()
    excluded_unknown_games: Mapped[int] = mapped_column(default=0)

    #: Each payload keeps totals, per-game summaries, sample dispersion and
    #: denominator-aware shooting rates. Percentages are never persisted as
    #: standalone columns; makes and attempts remain reconstructable.
    production_with: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    production_without: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    descriptive_deltas: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    uncertainty: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    provenance: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)

    data_layer: Mapped[str] = mapped_column(
        String(32), default="observations", server_default="observations"
    )
    claim_type: Mapped[str] = mapped_column(
        String(32), default="descriptive", server_default="descriptive"
    )
    membership_method: Mapped[str] = mapped_column(String(64))
    evidence_version: Mapped[str] = mapped_column(String(64))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    schedule_version: Mapped[str] = mapped_column(String(64))
    schedule_refreshed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    beneficiary: Mapped[Player] = relationship(foreign_keys=[beneficiary_player_id])
    absent_player: Mapped[Player] = relationship(foreign_keys=[absent_player_id])
    team: Mapped[NbaTeam] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<AbsenceSplit beneficiary={self.beneficiary_player_id} "
            f"absent={self.absent_player_id} season={self.season}>"
        )
