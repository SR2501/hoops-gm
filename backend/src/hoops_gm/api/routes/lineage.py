"""Refresh lineage: the cohort-matching contract for schedule/projection/model versions.

Read-only from the API's perspective. The registry is written by producers
(``import_schedule`` today; later ``quant``'s projection and model pipelines)
directly through ``hoops_gm.db.lineage.record_refresh`` inside their own
transaction, not through this router. What the API exposes is the two
questions a downstream consumer actually has: what is current, and does my
claimed cohort still match it. It does not compute or approve anything.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from hoops_gm.api.deps import SessionDep
from hoops_gm.db.lineage import (
    CohortStatus,
    check_cohort,
    check_refresh_claim,
    verify_refresh,
)
from hoops_gm.db.models.enums import RefreshArtifactType
from hoops_gm.db.models.lineage import RefreshRun

router = APIRouter(prefix="/lineage", tags=["lineage"])


class CurrentRefreshResponse(BaseModel):
    """The latest registered refresh that still verifies as current."""

    artifact_type: RefreshArtifactType
    artifact_key: str
    version: str
    season: str | None
    source: str
    summary: dict[str, object]
    refreshed_at: datetime


class ArtifactClaim(BaseModel):
    """One exact keyed and season-scoped lineage claim."""

    model_config = ConfigDict(extra="forbid")

    artifact_type: RefreshArtifactType
    artifact_key: str
    version: str
    season: str | None = None


class CohortRequest(BaseModel):
    """A caller's legacy broad versions or exact keyed lineage claims."""

    model_config = ConfigDict(extra="forbid")

    schedule_version: str | None = None
    model_version: str | None = None
    projection_version: str | None = None
    claims: list[ArtifactClaim] = Field(default_factory=list)


class CohortCheckResponse(BaseModel):
    """The verdict for one claimed version against the current registry."""

    artifact_type: RefreshArtifactType
    artifact_key: str
    season: str | None
    claimed_version: str
    status: CohortStatus
    #: None when persisted facts invalidate the latest registered refresh.
    #: A recomputed but unregistered content hash is never returned as current.
    current_version: str | None
    current_refreshed_at: datetime | None


class CohortResponse(BaseModel):
    checks: list[CohortCheckResponse]
    #: True only when at least one field was checked and every checked field
    #: is "current". An empty claim (no fields supplied) asserts nothing and
    #: is never accepted.
    accepted: bool


@router.get(
    "/current",
    response_model=list[CurrentRefreshResponse],
    summary="The verified current refresh for each keyed artifact scope",
)
def list_current(session: SessionDep) -> list[CurrentRefreshResponse]:
    rows = session.scalars(
        select(RefreshRun).order_by(
            RefreshRun.artifact_type,
            RefreshRun.artifact_key,
            RefreshRun.season_key,
            RefreshRun.refreshed_at.desc(),
            RefreshRun.id.desc(),
        )
    ).all()
    responses: list[CurrentRefreshResponse] = []
    seen: set[tuple[RefreshArtifactType, str, str]] = set()
    for run in rows:
        scope = (run.artifact_type, run.artifact_key, run.season_key)
        if scope in seen:
            continue
        seen.add(scope)
        verification = verify_refresh(session, run)
        if not verification.is_current:
            continue
        responses.append(
            CurrentRefreshResponse(
                artifact_type=run.artifact_type,
                artifact_key=run.artifact_key,
                version=run.version,
                season=run.season,
                source=run.source,
                summary=run.summary,
                refreshed_at=run.refreshed_at,
            )
        )
    return responses


@router.post(
    "/validate",
    response_model=CohortResponse,
    summary="Check whether a claimed schedule/projection/model cohort is still current",
)
def validate(payload: CohortRequest, session: SessionDep) -> CohortResponse:
    """Report per-field freshness. Never raises on a mismatch.

    Rejecting a stale or unknown cohort is the caller's policy decision (for
    example, ``quant`` refusing to persist a value computed against a
    superseded schedule); this endpoint only supplies the facts the decision
    rests on.
    """
    checks: list[CohortCheckResponse] = [
        CohortCheckResponse(
            artifact_type=result.artifact_type,
            artifact_key=(
                "nba-schedule"
                if result.artifact_type is RefreshArtifactType.SCHEDULE
                else "default"
            ),
            season=None,
            claimed_version=result.claimed_version,
            status=result.status,
            current_version=result.current_version,
            current_refreshed_at=result.current_refreshed_at,
        )
        for result in check_cohort(
            session,
            schedule_version=payload.schedule_version,
            model_version=payload.model_version,
            projection_version=payload.projection_version,
        )
    ]
    for claim in payload.claims:
        result = check_refresh_claim(
            session,
            artifact_type=claim.artifact_type,
            artifact_key=claim.artifact_key,
            claimed_version=claim.version,
            season=claim.season,
        )
        checks.append(
            CohortCheckResponse(
                artifact_type=claim.artifact_type,
                artifact_key=claim.artifact_key,
                season=claim.season,
                claimed_version=claim.version,
                status=result.status,
                current_version=result.current_version,
                current_refreshed_at=result.current_refreshed_at,
            )
        )
    accepted = bool(checks) and all(check.status == "current" for check in checks)
    return CohortResponse(checks=checks, accepted=accepted)
