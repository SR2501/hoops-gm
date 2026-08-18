"""Refresh lineage: provenance for the version strings other tables carry.

``opponent_context`` and ``off_night_slates`` (``schedule_context.py``) already
stamp every row with ``model_version`` and ``schedule_version`` — the
versioning seam the plan requires: every value carries its input versions.
What was missing is a place those version strings come *from*: a registry of
when a schedule, projection, or model was last (re)computed, so a downstream
consumer can ask "is this the current cohort" instead of trusting whatever
string it happens to have been handed.

This table is deliberately inert with respect to what a version *means*. It
does not compute ``p(play)``, opponent quality, or strength-of-schedule
convergence — see ADR-009, ADR-011 and ADR-012, none of which this touches. It
only answers three questions: what is the current version per artifact type,
when was it last refreshed, and does a caller's claimed version combination
still match. That is the entire contract; see ``hoops_gm.db.lineage`` for the
service functions built on top of it.

**Ownership boundary.** This table and its service functions are
``backend``-owned persistence, same as ``schedule_context.py``'s schema even
though ``quant`` defines the fields it carries (ownership matrix). Deciding
*which* SOS formulation, availability model, or projection blend is current
enough to trust remains ``quant``'s call under the Model gate — this registry
only lets that decision be checked mechanically once made, and it never
manufactures a version on a producer's behalf.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hoops_gm.db.base import Base, IntPk, TimestampMixin, UTCDateTime, portable_enum
from hoops_gm.db.models.enums import RefreshArtifactType


class RefreshRun(IntPk, TimestampMixin, Base):
    """One registered refresh of a versioned artifact.

    Idempotent by ``(artifact_type, artifact_key, version)``: re-registering
    the same version touches ``refreshed_at`` and ``summary`` on the existing
    row rather than creating a duplicate. History is retained; old versions
    are never deleted. "What is current now" is the latest row for the
    requested artifact type, key, and optional season — see
    ``hoops_gm.db.lineage.current_refresh``.
    """

    __tablename__ = "refresh_runs"
    __table_args__ = (
        UniqueConstraint(
            "artifact_type",
            "artifact_key",
            "version",
            name="uq_refresh_runs_type_key_version",
        ),
        Index(
            "ix_refresh_runs_current",
            "artifact_type",
            "artifact_key",
            "season",
            "refreshed_at",
        ),
    )

    artifact_type: Mapped[RefreshArtifactType] = mapped_column(
        portable_enum(RefreshArtifactType, "refresh_artifact_type")
    )
    #: Stable producer-defined identity within an artifact type. The default
    #: preserves the original one-stream-per-type contract.
    artifact_key: Mapped[str] = mapped_column(String(64), default="default")
    #: Opaque version label, matched byte-for-byte against the same string a
    #: consumer stamps on its own rows (e.g. ``opponent_context.schedule_version``).
    #: This registry never interprets it.
    version: Mapped[str] = mapped_column(String(64))
    #: NBA season this refresh pertains to. Left null for artifacts that are
    #: not season-scoped.
    season: Mapped[str | None] = mapped_column(String(9), nullable=True)
    #: Free-text description of what produced this refresh — an adapter name,
    #: a training job identifier. Provenance, not a foreign key: the producer
    #: is not always a row in this database.
    source: Mapped[str] = mapped_column(String(255))
    #: Counts and other refresh metadata the producer finds useful to record
    #: (rows created/updated, row counts). Never load-bearing for the cohort
    #: check itself — only the artifact scope, version, and refresh time are.
    summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    refreshed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<RefreshRun {self.artifact_type}:{self.artifact_key}="
            f"{self.version} at={self.refreshed_at}>"
        )
