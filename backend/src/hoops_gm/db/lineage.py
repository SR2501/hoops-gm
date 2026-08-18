"""Cohort lineage service: recording refreshes and validating claimed versions.

Plain functions over a ``Session`` rather than a class — there is no state
here beyond what is in the database, the same shape ``ingest/importers.py``
already uses for idempotent writes.

**What this is not.** It does not decide which schedule, projection, or model
version *should* be current, does not compute p(play) or opponent quality, and
does not implement strength-of-schedule convergence (ADR-011). It only
registers what producers say they refreshed and reports, mechanically,
whether a caller's claimed version still matches. That decision — and the
formulation of any future model or projection — stays with the owning
specialist agent (``data-engineer`` for schedule facts, ``quant`` for
projections and models) under the Adapter/Model gates.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import RefreshArtifactType
from hoops_gm.db.models.lineage import RefreshRun

CohortStatus = Literal["current", "stale", "unknown"]


class _SeasonNotSpecified:
    pass


_SEASON_NOT_SPECIFIED = _SeasonNotSpecified()


def content_fingerprint(parts: Iterable[str]) -> str:
    """A short, deterministic fingerprint over an ordered sequence of strings.

    Used to derive a ``version`` label that is stable across re-runs which
    change nothing and changes whenever the underlying facts do — the same
    idempotency-by-natural-key discipline ``ingest/importers.py`` already
    applies to individual rows, applied one level up to "what does the whole
    artifact currently look like". Not a security boundary; truncated to 16
    hex characters purely to keep the label short and comparable by eye.
    """

    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]


def record_refresh(
    session: Session,
    *,
    artifact_type: RefreshArtifactType,
    artifact_key: str = "default",
    version: str,
    source: str,
    season: str | None = None,
    summary: Mapping[str, object] | None = None,
    refreshed_at: datetime | None = None,
) -> RefreshRun:
    """Register that an artifact was (re)computed at ``version``.

    Idempotent by ``(artifact_type, artifact_key, version)``. The default key
    preserves the original contract for existing callers. Does not commit;
    callers manage their own transaction boundary (see ``db/session.py``).
    """

    when = refreshed_at if refreshed_at is not None else datetime.now(UTC)
    existing = session.scalar(
        select(RefreshRun).where(
            RefreshRun.artifact_type == artifact_type,
            RefreshRun.artifact_key == artifact_key,
            RefreshRun.version == version,
        )
    )
    if existing is not None:
        existing.refreshed_at = when
        existing.source = source
        if season is not None:
            existing.season = season
        if summary is not None:
            existing.summary = dict(summary)
        session.flush()
        return existing

    run = RefreshRun(
        artifact_type=artifact_type,
        artifact_key=artifact_key,
        version=version,
        season=season,
        source=source,
        summary=dict(summary) if summary is not None else {},
        refreshed_at=when,
    )
    session.add(run)
    session.flush()
    return run


def current_refresh(
    session: Session,
    artifact_type: RefreshArtifactType,
    *,
    artifact_key: str = "default",
    season: str | _SeasonNotSpecified | None = _SEASON_NOT_SPECIFIED,
) -> RefreshRun | None:
    """The latest row for one artifact type/key and optional season.

    ``None`` means no producer has ever registered a refresh for this
    scope. Omitting ``season`` searches all seasons; passing ``None`` matches
    only unscoped rows.
    """

    filters = [
        RefreshRun.artifact_type == artifact_type,
        RefreshRun.artifact_key == artifact_key,
    ]
    if not isinstance(season, _SeasonNotSpecified):
        filters.append(
            RefreshRun.season.is_(None) if season is None else RefreshRun.season == season
        )
    return session.scalar(
        select(RefreshRun)
        .where(*filters)
        .order_by(RefreshRun.refreshed_at.desc(), RefreshRun.id.desc())
        .limit(1)
    )


@dataclass(frozen=True)
class CohortCheck:
    """The verdict for one claimed version against the current registry."""

    artifact_type: RefreshArtifactType
    claimed_version: str
    status: CohortStatus
    current_version: str | None
    current_refreshed_at: datetime | None


def check_cohort(
    session: Session,
    *,
    schedule_version: str | None = None,
    model_version: str | None = None,
    projection_version: str | None = None,
) -> list[CohortCheck]:
    """Compare claimed version strings against the current registered refresh.

    Only the artifact types actually supplied are checked — omitting a field
    means the caller is not asserting anything about it, not that it is
    automatically accepted. This reports per artifact whether the claim is
    ``"current"``, ``"stale"`` (registered, but superseded by a later
    refresh), or ``"unknown"`` (nothing has ever been registered for that
    artifact type, so there is no baseline to compare against). It does not
    decide whether a mismatch is fatal; that policy belongs to the caller
    (e.g. ``quant`` refusing to persist a valuation computed against a stale
    schedule cohort).
    """

    claims: tuple[tuple[RefreshArtifactType, str | None], ...] = (
        (RefreshArtifactType.SCHEDULE, schedule_version),
        (RefreshArtifactType.MODEL, model_version),
        (RefreshArtifactType.PROJECTION, projection_version),
    )
    results: list[CohortCheck] = []
    for artifact_type, claimed in claims:
        if claimed is None:
            continue
        current = current_refresh(session, artifact_type)
        if current is None:
            results.append(CohortCheck(artifact_type, claimed, "unknown", None, None))
        elif current.version == claimed:
            results.append(
                CohortCheck(
                    artifact_type, claimed, "current", current.version, current.refreshed_at
                )
            )
        else:
            results.append(
                CohortCheck(artifact_type, claimed, "stale", current.version, current.refreshed_at)
            )
    return results
