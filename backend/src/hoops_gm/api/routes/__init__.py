"""Route modules.

``health`` and ``userscript`` are mounted unversioned; probes are
operational and the userscript file is a static-file surface, neither part
of the ``/api/v1`` JSON API contract. Everything else hangs off ``/api/v1``.
"""

from fastapi import APIRouter

from hoops_gm.api.routes import (
    bridge,
    deadline_calendar,
    drafts,
    health,
    lineage,
    meta,
    projections,
    schedule_grid,
    userscript,
)

#: Operational endpoints, unversioned.
ops_router = APIRouter()
ops_router.include_router(health.router)
ops_router.include_router(userscript.router)

#: The versioned API surface. New routers are added here.
api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(meta.router)
api_v1_router.include_router(bridge.router)
api_v1_router.include_router(lineage.router)
api_v1_router.include_router(deadline_calendar.router)
api_v1_router.include_router(schedule_grid.router)
api_v1_router.include_router(projections.router)
api_v1_router.include_router(drafts.router)

__all__ = ["api_v1_router", "ops_router"]
