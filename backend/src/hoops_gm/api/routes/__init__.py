"""Route modules.

``health`` is mounted unversioned; probes are operational, not part of the API
contract. Everything else hangs off ``/api/v1``.
"""

from fastapi import APIRouter

from hoops_gm.api.routes import bridge, health, lineage, meta

#: Operational endpoints, unversioned.
ops_router = APIRouter()
ops_router.include_router(health.router)

#: The versioned API surface. New routers are added here.
api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(meta.router)
api_v1_router.include_router(bridge.router)
api_v1_router.include_router(lineage.router)

__all__ = ["api_v1_router", "ops_router"]
