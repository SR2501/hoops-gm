"""Projections: the generic CSV import boundary — ``csv-importer``, Phase 5.

No source publishes projections through an API (plan.md: FantasyPros is a
free CSV, Hashtag is Patreon-gated, Basketball Monster is a paid CSV export,
DARKO is historical CSV only). A CSV drop is therefore the whole integration
surface, and everything downstream of it — blending, expected-games fusion,
valuation — depends on this boundary decomposing what the source published
rather than re-publishing it whole.

**ADR-002 is the shape of this module.** Per-game production and a source's
embedded games-played assumption are modelled independently and fused only at
``expected-games``, a later phase this module does not implement. That means
three things structurally:

1. ``projections`` holds **only** per-game rates. Nothing here is a seasonal
   total, and nothing here is an expected-games number.
2. ``source_games_played_assumptions`` holds the games-played number the
   source's own rates were built against — kept in a separate table, one-to-
   one with a projection row, so nothing downstream can reach it by accident
   while reading a rate. It exists to be *overridden*, not blended.
3. ``projection_imports`` is versioned rather than mutated. Re-importing
   byte-identical content converges onto the same row; a source publishing an
   updated file creates a new one. "Which numbers did we walk in with" stays a
   query.

**Percentage categories are volume-weighted impact, not raw percentage** (the
single most common bug in homebrew fantasy tools — AGENTS.md). ``projections``
therefore stores makes and attempts per game, never a bare shooting
percentage, mirroring ``BoxScoreMixin`` in ``stats.py``. A source that
publishes only a percentage without volume cannot be decomposed and is a
parser-level validation warning (``hoops_gm.ingest.projections``), not a
silently invented attempt count here.

**Source identity reuses the existing crosswalk**, rather than inventing a
second one. ``ProjectionSource.source`` is an :class:`ExternalSource` member —
the same vocabulary ``player_external_ids.source`` already uses for
FantasyPros, Hashtag, Basketball Monster and DARKO — so a projection row and
its identity match are the same source by construction and cannot drift
apart.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, UTCDateTime, portable_enum
from hoops_gm.db.models.enums import ExternalSource, ScoringType

if TYPE_CHECKING:
    from hoops_gm.db.models.identity import Player


class ProjectionSource(IntPk, TimestampMixin, Base):
    """A registered projection publisher.

    One row per :class:`ExternalSource`, not one row per season or per file —
    ``projection_imports`` is where the per-file versioning lives. Owned
    jointly by ``quant`` and ``data-engineer`` (ownership.md): the column
    mapping in a profile is a data-engineering concern, but the assumed
    scoring format matters to blending, which is ``quant``'s.
    """

    __tablename__ = "projection_sources"
    __table_args__ = (UniqueConstraint("source", name="uq_projection_sources_source"),)

    source: Mapped[ExternalSource] = mapped_column(
        portable_enum(ExternalSource, "external_source"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(128))
    #: Scoring format the source's *published* numbers assume, when known.
    #: Plan.md: "most published AAV is built for points leagues or default
    #: 9-cat, not this league's specific categories" — the same caution
    #: applies to projections, and blending (a later phase) needs to know
    #: before it adjusts or down-weights a source rather than mixing formats
    #: silently.
    assumed_scoring_type: Mapped[ScoringType | None] = mapped_column(
        portable_enum(ScoringType, "scoring_type")
    )
    notes: Mapped[str | None] = mapped_column(Text)

    imports: Mapped[list[ProjectionImport]] = relationship(
        back_populates="source_row", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ProjectionSource {self.source}>"


class ProjectionImport(IntPk, TimestampMixin, Base):
    """One versioned snapshot of a source's CSV, imported at a point in time.

    Deliberately never overwritten in place. ``(source_id, season,
    content_sha256)`` is the natural key a re-run converges on — the same
    byte-identical file for the same source and season resolves to the same
    import row — so a source publishing an *updated* file creates a new row
    rather than mutating history out from under whatever already blended the
    old one. Season is part of the key because many CSVs do not embed it in
    their bytes; reusing one file as a template for a later season must not
    silently return the earlier season's import.

    Row counts are the import's own audit trail: ``row_count`` is every data
    row the file contained, and ``matched_count`` / ``needs_review_count`` /
    ``unmatched_count`` partition it by identity-resolution outcome exactly as
    ``hoops_gm.identity.report`` reports it. ``rejected_count`` is rows the
    parser refused before identity resolution ever ran — unparsable numbers,
    a missing name, an impossible games-played value, or a duplicate name
    within the same file. None of the four resolution states silently
    disappears.
    """

    __tablename__ = "projection_imports"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "season",
            "content_sha256",
            name="uq_projection_imports_source_season_checksum",
        ),
        Index("ix_projection_imports_source_season", "source_id", "season"),
        CheckConstraint("row_count >= 0", name="row_count_non_negative"),
        CheckConstraint("matched_count >= 0", name="matched_count_non_negative"),
        CheckConstraint("needs_review_count >= 0", name="needs_review_count_non_negative"),
        CheckConstraint("unmatched_count >= 0", name="unmatched_count_non_negative"),
        CheckConstraint("rejected_count >= 0", name="rejected_count_non_negative"),
    )

    source_id: Mapped[int] = mapped_column(
        ForeignKey("projection_sources.id", ondelete="CASCADE"), index=True
    )
    season: Mapped[str] = mapped_column(String(9), index=True)
    #: Logical import time. Distinct from ``created_at``/``updated_at`` (row
    #: bookkeeping) so a caller replaying an older capture can state when the
    #: source actually published it, the same distinction ``rawstore.py``
    #: draws between ``fetched_at`` and row timestamps.
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    needs_review_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    #: Per-import override of the source's default assumed scoring format,
    #: for a one-off file built to a different format than usual.
    assumed_scoring_type: Mapped[ScoringType | None] = mapped_column(
        portable_enum(ScoringType, "scoring_type")
    )
    #: Optional pointer into a raw payload store (``ingest/rawstore.py``) for
    #: the untouched bytes. Never the bytes themselves: projection data is
    #: personal-use only (plan.md) and a purchased CSV has no business inside
    #: a row every backup and every ``SELECT *`` carries.
    raw_payload_ref: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    source_row: Mapped[ProjectionSource] = relationship(back_populates="imports")
    projections: Mapped[list[Projection]] = relationship(
        back_populates="projection_import", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ProjectionImport source={self.source_id} season={self.season!r}>"


class Projection(IntPk, TimestampMixin, Base):
    """One player's per-game production rate from one projection import.

    **Rates only** (ADR-002). Nothing here is a season total and nothing here
    is an expected-games number — those are ``expected-games``'s job, a later
    phase, and it consumes this table plus the availability model rather than
    a column added here.

    Makes and attempts are stored, never a bare percentage — the CHECK
    constraints below make "makes exceed attempts" inexpressible rather than
    merely validated at parse time, the same "make it inexpressible" pattern
    ``db/base.py`` uses for enum values.
    """

    __tablename__ = "projections"
    __table_args__ = (
        UniqueConstraint("projection_import_id", "player_id", name="uq_projections_import_player"),
        Index("ix_projections_player_season", "player_id", "season"),
        CheckConstraint(
            "field_goals_made_per_game IS NULL OR field_goals_attempted_per_game IS NULL "
            "OR field_goals_made_per_game <= field_goals_attempted_per_game + 0.001",
            name="fg_made_within_attempted",
        ),
        CheckConstraint(
            "three_pointers_made_per_game IS NULL OR three_pointers_attempted_per_game IS NULL "
            "OR three_pointers_made_per_game <= three_pointers_attempted_per_game + 0.001",
            name="fg3_made_within_attempted",
        ),
        CheckConstraint(
            "free_throws_made_per_game IS NULL OR free_throws_attempted_per_game IS NULL "
            "OR free_throws_made_per_game <= free_throws_attempted_per_game + 0.001",
            name="ft_made_within_attempted",
        ),
    )

    projection_import_id: Mapped[int] = mapped_column(
        ForeignKey("projection_imports.id", ondelete="CASCADE"), index=True
    )
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    #: Denormalised from the import for direct querying without a join, the
    #: same choice ``NbaGame``/``PlayerSeasonStat``/``TeamScheduleEntry`` make
    #: for ``season``.
    season: Mapped[str] = mapped_column(String(9), index=True)

    minutes_per_game: Mapped[float | None] = mapped_column()
    points_per_game: Mapped[float | None] = mapped_column()
    offensive_rebounds_per_game: Mapped[float | None] = mapped_column()
    defensive_rebounds_per_game: Mapped[float | None] = mapped_column()
    rebounds_per_game: Mapped[float | None] = mapped_column()
    assists_per_game: Mapped[float | None] = mapped_column()
    steals_per_game: Mapped[float | None] = mapped_column()
    blocks_per_game: Mapped[float | None] = mapped_column()
    turnovers_per_game: Mapped[float | None] = mapped_column()
    personal_fouls_per_game: Mapped[float | None] = mapped_column()
    field_goals_made_per_game: Mapped[float | None] = mapped_column()
    field_goals_attempted_per_game: Mapped[float | None] = mapped_column()
    three_pointers_made_per_game: Mapped[float | None] = mapped_column()
    three_pointers_attempted_per_game: Mapped[float | None] = mapped_column()
    free_throws_made_per_game: Mapped[float | None] = mapped_column()
    free_throws_attempted_per_game: Mapped[float | None] = mapped_column()

    #: The source row exactly as parsed, before normalisation, keyed by the
    #: profile's canonical field names. Kept so a disputed number can be
    #: traced back to precisely what the source published, the same
    #: "preserve raw before normalising" reasoning as ``rawstore.py``, scaled
    #: down to a single CSV row rather than a multi-megabyte payload.
    raw_row: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    projection_import: Mapped[ProjectionImport] = relationship(back_populates="projections")
    player: Mapped[Player] = relationship()
    games_played_assumption: Mapped[SourceGamesPlayedAssumption | None] = relationship(
        back_populates="projection", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Projection player={self.player_id} import={self.projection_import_id}>"


class SourceGamesPlayedAssumption(IntPk, TimestampMixin, Base):
    """The games-played number a source's per-game rates were built against.

    ADR-002's separation, made structural: this is the *only* place a
    source's durability guess is recorded, and it is one-to-one with a
    ``projections`` row rather than a column on it, so nothing can read a
    per-game rate and pick up an unrelated availability assumption by
    accident. The availability model overrides this; it never blends with it.

    Not every source publishes one — a manual/ad-hoc sheet may give only
    rates — so this row is created only when the source stated something,
    never invented to fill the shape.
    """

    __tablename__ = "source_games_played_assumptions"
    __table_args__ = (
        UniqueConstraint("projection_id", name="uq_source_games_played_assumptions_projection"),
        CheckConstraint(
            "assumed_games_played IS NULL "
            "OR (assumed_games_played >= 0 AND assumed_games_played <= 100)",
            name="assumed_games_played_range",
        ),
    )

    projection_id: Mapped[int] = mapped_column(ForeignKey("projections.id", ondelete="CASCADE"))
    assumed_games_played: Mapped[float | None] = mapped_column()
    #: The source's own text for this, kept verbatim ("68", "68.0", "68 GP")
    #: so a later re-derivation is possible without re-parsing the CSV.
    assumed_games_played_raw: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)

    projection: Mapped[Projection] = relationship(back_populates="games_played_assumption")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SourceGamesPlayedAssumption projection={self.projection_id}>"
