"""League settings snapshots: the versioned, source-attributed rules boundary.

`league-settings-ingest` (docs/backlog.md) is the prerequisite for all timing
intelligence: lineup lock type, waiver period/processing/claim mechanism,
games-played caps, roster/IR limits, scoring-period boundaries, trade
deadline, playoff periods and keeper rules. None of the deadline, games-cap or
notification work later in the plan can be built without first knowing the
league's actual rules, and — per docs/league/2025-26-rules-baseline.md — the
2025-26 values are historical reference only and must never silently stand in
for an unverified 2026-27 setting.

Two things this table has to guarantee, because getting either wrong poisons
everything downstream of it:

**Absent stays absent.** The verified `getLeagueInfo` payload returns roster
and scoring-period settings but no waiver, lineup-lock, games-cap, trade,
playoff or keeper fields. The bridge is the documented fallback for whatever
it omits. So a field a source did not supply must be storable as
"unknown", not filled from the historical baseline document or from any other
league's settings, and nothing here may quietly default a games cap, a waiver
mechanism or a keeper rule to a plausible-looking value nobody actually
observed. The ingestion boundary (owned by whoever builds it against the
verified endpoint shape) is responsible for writing an explicit `null` rather
than omitting a key or inventing a value — this table does not and cannot
enforce that on its own, because a JSON document's internal shape is not a
database constraint.

**Source attribution is per field, not per snapshot.** The official API may
answer some of these fields and the read-only bridge may be the only source
for the rest (or vice versa, or a field may come from neither and stay
unknown) — see ADR-004's tiering. A single `source` column on the row would
force every field to share one provenance even when they did not, which is
exactly the "team: (N/A)" scalar-confidence mistake `player_external_ids`
(identity.py) already had to fix with per-field evidence columns. Here the
per-field granularity lives inside the `source_summary` document rather than
as separate columns, because the set of fields is a settings vocabulary the
typed ingestion boundary owns and validates — not a fixed, enumerable set of
database columns. Adding many speculative typed columns for every rule the
plan lists would freeze that vocabulary at the schema layer for a value that
changes at most once a year and is trivially representable as data.

**Immutable and versioned, never updated in place.** Same discipline as
``LeagueScoringProfile`` (league.py): a settings change — the commissioner
moves the trade deadline, a games cap is corrected — inserts the next
``version`` row. It never rewrites an existing one. Anything that later reads
"what were this league's settings when a valuation/deadline/decision was
computed" takes the snapshot id as of that moment, and that answer survives
the settings changing later. `schema_version` is a different axis entirely:
it names the *shape* of the ``settings`` document (which top-level keys and
their nesting exist), so the ingestion boundary can evolve the document
without every historical row appearing to retroactively gain fields it never
had.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, UTCDateTime

if TYPE_CHECKING:
    from hoops_gm.db.models.league import League


class LeagueSettingsSnapshot(IntPk, TimestampMixin, Base):
    """One immutable, source-attributed capture of a league's rules.

    ``settings`` is the normalized document: lineup lock type, waiver
    period/processing/claim mechanism, games-played caps, roster/IR limits,
    scoring-period boundaries, trade deadline, playoff periods, keeper rules.
    A field the source did not supply is present with a ``null`` value, never
    omitted and never filled from a historical baseline — see the module
    docstring. This table does not normalize ``scoring_periods`` or
    ``roster_slots`` (league.py) from it; that materialization, if it happens
    at all, is a separate, later concern and downstream of this boundary, not
    part of it.

    ``source_summary`` indexes each concern's evidence from the validated
    settings document so provenance can be inspected without understanding the
    whole versioned document shape. A single snapshot may legitimately mix
    sources across its fields.

    ``source_payload_sha256`` is the hash of the raw upstream payload(s) this
    snapshot was derived from — cheap evidence, independent of anything this
    row claims about itself, that a re-ingest actually saw new upstream bytes
    rather than re-deriving an identical snapshot from a caching bug.

    Never updated in place: a settings change is the next ``version`` row.
    """

    __tablename__ = "league_settings_snapshots"
    __table_args__ = (
        UniqueConstraint("league_id", "version", name="uq_league_settings_snapshots_version"),
        CheckConstraint("version >= 1", name="version_positive"),
        # SHA-256 hex digest length, checked portably (length() is ANSI SQL,
        # not a dialect-specific extension) rather than trusting every caller
        # to have hashed correctly.
        CheckConstraint("length(source_payload_sha256) = 64", name="source_payload_sha256_length"),
        Index(
            "ix_league_settings_snapshots_league_observed_at",
            "league_id",
            "observed_at",
        ),
    )

    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    #: Monotonically assigned by the writer, starting at 1. Uniqueness with
    #: ``league_id`` is what makes a snapshot addressable and immutable; ever
    #: reusing a version for a league is a bug in the caller, not something
    #: this table can detect on its own beyond rejecting the duplicate insert.
    version: Mapped[int] = mapped_column(default=1)
    #: Names the shape of ``settings``/``source_summary`` (which top-level
    #: keys exist and how they nest), independent of ``version``. Bump this
    #: when the ingestion boundary's document shape changes; bump ``version``
    #: when the league's actual rules change under an unchanged shape.
    schema_version: Mapped[str] = mapped_column(String(32))
    #: The settings document. Absent-from-source fields are present with a
    #: JSON ``null``, not omitted — see the module docstring. Deliberately
    #: untyped at this layer: the typed ingestion boundary validates the
    #: shape before a row ever reaches this table.
    settings: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    #: Per-field provenance keyed by the same field paths as ``settings``.
    #: A field may legitimately be attributed to the Fantrax official API,
    #: the read-only bridge, or neither (unknown) — source attribution is not
    #: uniform across one snapshot.
    source_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    #: SHA-256 hex digest of the raw upstream payload(s) behind this snapshot.
    source_payload_sha256: Mapped[str] = mapped_column(String(64))
    #: When the upstream data was observed — the source's "as of" moment, not
    #: merely when this row was written (``created_at`` already covers that,
    #: and a backfill could observe old data long after the fact).
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    league: Mapped[League] = relationship(back_populates="settings_snapshots")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LeagueSettingsSnapshot league={self.league_id} v{self.version}>"
