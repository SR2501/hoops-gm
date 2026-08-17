"""Service metadata.

The first versioned endpoint. It exists so the frontend has a real, typed call
to make against a real contract from day one — a dashboard that has never
successfully talked to the backend is not a skeleton, it is a mock.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hoops_gm import __version__
from hoops_gm.api.deps import SettingsDep

router = APIRouter(prefix="/meta", tags=["meta"])


class MetaResponse(BaseModel):
    service: str
    version: str
    environment: str
    #: Target NBA season, in the ``2026-27`` form every upstream uses.
    season: str = Field(default="2026-27")
    #: What of the plan is actually implemented. Honest by construction: it is
    #: read from the schema, not hand-maintained.
    entity_groups: list[str]


@router.get("", response_model=MetaResponse, summary="Service metadata")
def meta(settings: SettingsDep) -> MetaResponse:
    return MetaResponse(
        service=settings.app_name,
        version=__version__,
        environment=settings.environment,
        entity_groups=["identity", "stats", "league", "schedule"],
    )
