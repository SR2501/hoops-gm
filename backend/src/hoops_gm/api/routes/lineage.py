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
from pydantic import BaseModel, ConfigDict

from hoops_gm.api.deps import SessionDep
from hoops_gm.db.lineage import CohortStatus, check_cohort, current_refresh
from hoops_gm.db.models.enums import RefreshArtifactType

router = APIRouter(prefix="/lineage", tags=["lineage"])


class CurrentRefreshResponse(BaseModel):
    """The latest registered refresh for one artifact type."""

    artifact_type: RefreshArtifactType
    version: str
    season: str | None
    source: str
    summary: dict[str, object]
    refreshed_at: datetime


class CohortRequest(BaseModel):
    """A caller's claimed version for each artifact type it depends on.

    Any field left unset is not checked — omitting it means the caller is not
    asserting anything about that artifact, not that it is automatically
    accepted.
    """

    model_config = ConfigDict(extra="forbid")

    schedule_version: str | None = None
    model_version: str | None = None
    projection_version: str | None = None


class CohortCheckResponse(BaseModel):
    """The verdict for one claimed version against the current registry."""

    artifact_type: RefreshArtifactType
    claimed_version: str
    status: CohortStatus
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
    summary="The current refresh registered for each artifact type",
)
def list_current(session: SessionDep) -> list[CurrentRefreshResponse]:
    responses: list[CurrentRefreshResponse] = []
    for artifact_type in RefreshArtifactType:
        run = current_refresh(session, artifact_type)
        if run is None:
            continue
        responses.append(
            CurrentRefreshResponse(
                artifact_type=run.artifact_type,
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
    checks = [
        CohortCheckResponse(
            artifact_type=result.artifact_type,
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
    accepted = bool(checks) and all(check.status == "current" for check in checks)
    return CohortResponse(checks=checks, accepted=accepted)
