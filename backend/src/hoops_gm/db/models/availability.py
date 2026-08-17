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

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, portable_enum
from hoops_gm.db.models.enums import (
    DnpReason,
    ExternalSource,
    ParticipationOutcome,
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
