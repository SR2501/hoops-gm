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


class AbsenceSplitComputationRun(IntPk, TimestampMixin, Base):
    """One complete successful absence-split computation, including empty ones."""

    __tablename__ = "absence_split_runs"
    __table_args__ = (
        UniqueConstraint(
            "season",
            "season_type",
            "evidence_version",
            "schedule_version",
            "input_fingerprint",
            name="uq_absence_split_runs_input",
        ),
        CheckConstraint("result_count >= 0", name="result_count_non_negative"),
        CheckConstraint(
            "skipped_one_sided_pairs >= 0",
            name="skipped_pairs_non_negative",
        ),
        Index(
            "ix_absence_split_runs_current",
            "season",
            "season_type",
            "evidence_version",
            "schedule_version",
            "id",
        ),
    )

    season: Mapped[str] = mapped_column(String(9))
    season_type: Mapped[SeasonType] = mapped_column(portable_enum(SeasonType, "season_type"))
    evidence_version: Mapped[str] = mapped_column(String(64))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    schedule_version: Mapped[str] = mapped_column(String(64))
    schedule_refreshed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    result_count: Mapped[int] = mapped_column(default=0)
    skipped_one_sided_pairs: Mapped[int] = mapped_column(default=0)

    splits: Mapped[list[AbsenceSplit]] = relationship(
        back_populates="computation_run",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<AbsenceSplitComputationRun season={self.season} "
            f"version={self.evidence_version} results={self.result_count}>"
        )


class AbsenceSplit(IntPk, TimestampMixin, Base):
    """Descriptive teammate production evidence from direct observations only."""

    __tablename__ = "absence_splits"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "beneficiary_player_id",
            "absent_player_id",
            "team_id",
            name="uq_absence_splits_run_pair",
        ),
        CheckConstraint(
            "beneficiary_player_id <> absent_player_id",
            name="distinct_players",
        ),
        CheckConstraint("games_with > 0", name="games_with_positive"),
        CheckConstraint("games_without > 0", name="games_without_positive"),
        CheckConstraint("observed_absence_games = games_without", name="all_absences_observed"),
        CheckConstraint("data_layer = 'observations'", name="observation_layer_only"),
        CheckConstraint("claim_type = 'descriptive'", name="descriptive_claim_only"),
        Index("ix_absence_splits_absent_player", "absent_player_id"),
        Index("ix_absence_splits_beneficiary_player", "beneficiary_player_id"),
        Index("ix_absence_splits_run", "run_id"),
        Index("ix_absence_splits_team", "team_id"),
    )

    run_id: Mapped[int] = mapped_column(ForeignKey("absence_split_runs.id", ondelete="CASCADE"))
    beneficiary_player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"))
    absent_player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"))
    team_id: Mapped[int] = mapped_column(ForeignKey("nba_teams.id"))

    games_with: Mapped[int] = mapped_column()
    games_without: Mapped[int] = mapped_column()
    observed_absence_games: Mapped[int] = mapped_column()

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

    computation_run: Mapped[AbsenceSplitComputationRun] = relationship(back_populates="splits")
    beneficiary: Mapped[Player] = relationship(foreign_keys=[beneficiary_player_id])
    absent_player: Mapped[Player] = relationship(foreign_keys=[absent_player_id])
    team: Mapped[NbaTeam] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<AbsenceSplit beneficiary={self.beneficiary_player_id} "
            f"absent={self.absent_player_id} run={self.run_id}>"
        )
