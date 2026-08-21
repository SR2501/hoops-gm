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

from datetime import date, datetime
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

from hoops_gm.db.base import Base, IntPk, TimestampMixin, UTCDateTime, portable_enum
from hoops_gm.db.models.enums import (
    Conference,
    ExternalSource,
    FieldEvidence,
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
    #: NBA's own positional label, verbatim from ``PlayerIndex`` — ``"G"``,
    #: ``"F-C"``, and so on. League-specific eligibility is a Fantrax concept
    #: and belongs to the league tables, not here.
    #:
    #: **This is a fact about the player, and it is coarse.** The source
    #: vocabulary is ``G/F/C`` plus hybrids and contains no ``PG``/``SG``/
    #: ``SF``/``PF`` — verified on 2026-08-20 against ``PlayerIndex``,
    #: ``CommonPlayerInfo`` and ``CommonTeamRoster``. So this separates a centre
    #: from a guard, which is what risk R7's third matching key needs, and it
    #: cannot express a Fantrax lineup slot.
    #:
    #: ``NULL`` means the source stated no position, which is a real observed
    #: condition (six 2026-27 rows, all ``FROM_YEAR`` 2026) and never a guess.
    primary_position: Mapped[str | None] = mapped_column(String(16))
    #: Where the position came from, as ``"<source>:<endpoint>"``. A stored
    #: attribute with no provenance cannot be refreshed deliberately, and this
    #: column exists so that a future second opinion — Fantrax's, a projection
    #: CSV's — is distinguishable from the NBA's rather than overwriting it
    #: invisibly.
    primary_position_source: Mapped[str | None] = mapped_column(String(48))
    #: The season the listing was read for. Position is stable but not
    #: immutable: 490 players shared between 2025-26 and 2026-27 carried
    #: identical positions, so a changed value is a real event and needs a
    #: season to be a change *from*.
    primary_position_season: Mapped[str | None] = mapped_column(String(9))
    #: When that reading was taken. **Refreshed on every crosswalk run, even
    #: when the position is unchanged**, because the useful question about a
    #: listed attribute is how fresh the reading is, not only when it last
    #: moved. The cost is that ``players.updated_at`` changes on every run for
    #: every matched player, so it stops distinguishing "this row changed
    #: meaningfully" from "the position was re-confirmed" — use this column,
    #: not ``updated_at``, to reason about position freshness.
    #:
    #: The four position columns are written together or not at all by
    #: ``import_player_positions``, and ``NbaPlayerPositionRecord.season`` is
    #: required so a caller cannot assemble an incomplete triple. There is
    #: deliberately **no** database CHECK enforcing that, so any other writer —
    #: including a plain ORM ``Player(primary_position="C")`` — can still
    #: produce one. SQLite can only add a CHECK by rebuilding the table, and
    #: ten foreign keys point into ``players`` with eight ``ON DELETE
    #: CASCADE``, so the rebuild deletes the crosswalk, the game logs, the
    #: participation ledger and the projections. Implemented, measured,
    #: reverted — see revision 0016.
    primary_position_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
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
    point at two people.

    The reverse is deliberately *not* unique, but it is not unconstrained
    either, and the distinction matters because two different things look
    alike here:

    * **Sibling identifiers across sources are normal.** Fantrax exposes
      ``statsIncId``, ``rotowireId`` and ``sportRadarId``; each is its own
      source and gets its own row. Nothing should prevent that.
    * **Superseded identifiers within one source are history.** When a source
      changes a player's identifier between seasons, the old row must be
      retained but must stop being the one joins pick up.

    Without that second constraint, two ``fantrax`` rows for one player make
    ``players JOIN player_external_ids ON source = 'fantrax'`` fan out, and
    every aggregate through the crosswalk silently double-counts.

    ``current_for_source`` enforces it portably: it holds the source value
    while the row is current and ``NULL`` once superseded, and
    ``(player_id, current_for_source)`` is unique. SQL treats NULLs as
    distinct on both dialects, so any number of superseded rows coexist while
    at most one current row per source survives. This is the same technique as
    ``player_season_stats.team_key``, and it is used in preference to a partial
    unique index because that would need ``sqlite_where`` and
    ``postgresql_where`` — dialect-specific DDL, in the table where ADR-001
    matters most.

    ``confidence`` and ``match_method`` exist so that the unmatched/low-
    confidence report required by Phase 2 is a query, not a re-derivation.
    Neither has a permissive default: ``match_method`` has no default at all,
    so a caller must state how it matched, and ``confidence`` defaults to
    ``0.0``. An earlier version defaulted to ``ANCHOR_ID`` and ``1.0``, so a
    forgotten field asserted the strongest possible provenance — matched on a
    shared identifier, fully confident — for a join where no shared identifier
    exists at all. On the project's highest-severity risk, the silent default
    must be the pessimistic one.

    ``is_manual_override`` is the resolver's stop sign: a human decision must
    survive the next automated pass.
    """

    __tablename__ = "player_external_ids"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_player_external_ids_source_ext"),
        UniqueConstraint("player_id", "current_for_source", name="uq_player_external_ids_current"),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="confidence_range",
        ),
        CheckConstraint(
            "current_for_source IS NULL OR current_for_source = source",
            name="current_marker_matches_source",
        ),
        Index("ix_player_external_ids_player_source", "player_id", "source"),
        Index("ix_player_external_ids_source_norm_name", "source", "normalized_name"),
    )

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    source: Mapped[ExternalSource] = mapped_column(portable_enum(ExternalSource, "external_source"))
    #: Equal to ``source`` while this is the identifier joins should use, and
    #: NULL once superseded. Carries the uniqueness a boolean flag could not
    #: without a dialect-specific partial index.
    current_for_source: Mapped[str | None] = mapped_column(String(48))
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

    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    match_method: Mapped[MatchMethod] = mapped_column(portable_enum(MatchMethod, "match_method"))
    is_manual_override: Mapped[bool] = mapped_column(default=False, index=True)

    #: Per-field match evidence. Phase 1 left open whether a single
    #: ``confidence`` float suffices; Phase 2 measured it against the real
    #: payload and it does not. 1,206 of the 1,788 Fantrax player rows carry
    #: ``team: "(N/A)"``, so for two thirds of the payload the team contributes
    #: no evidence at all — and a scalar cannot distinguish that from a team
    #: that is known and contradicts. The first is an ordinary free agent and
    #: probably a correct match; the second is probably two different people.
    #:
    #: Stored as four three-valued columns rather than one JSON blob so that
    #: the unmatched/low-confidence report stays a plain SQL query on both
    #: dialects, which is the same reason ``portable_enum`` exists.
    #:
    #: All default to ``UNKNOWN``, and the default is a **server** default as
    #: well as a Python one. That is deliberate: it keeps the pessimistic
    #: default true for a raw ``text()`` insert, a data migration or a bulk
    #: load, none of which go through the ORM. A caller who states nothing has
    #: claimed nothing — the same property ``confidence`` and ``match_method``
    #: already have, extended to the paths that bypass Python.
    name_evidence: Mapped[FieldEvidence] = mapped_column(
        portable_enum(FieldEvidence, "name_evidence"),
        default=FieldEvidence.UNKNOWN,
        server_default=FieldEvidence.UNKNOWN.value,
    )
    team_evidence: Mapped[FieldEvidence] = mapped_column(
        portable_enum(FieldEvidence, "team_evidence"),
        default=FieldEvidence.UNKNOWN,
        server_default=FieldEvidence.UNKNOWN.value,
    )
    position_evidence: Mapped[FieldEvidence] = mapped_column(
        portable_enum(FieldEvidence, "position_evidence"),
        default=FieldEvidence.UNKNOWN,
        server_default=FieldEvidence.UNKNOWN.value,
    )
    suffix_evidence: Mapped[FieldEvidence] = mapped_column(
        portable_enum(FieldEvidence, "suffix_evidence"),
        default=FieldEvidence.UNKNOWN,
        server_default=FieldEvidence.UNKNOWN.value,
    )

    #: Set when a human has looked at this row, whether or not they changed it.
    reviewed_at: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    player: Mapped[Player] = relationship(back_populates="external_ids")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PlayerExternalId {self.source}:{self.external_id} -> {self.player_id}>"
