"""System status: which external services are currently degraded (drives the
header health indicator). Signal-driven from the in-process ServiceHealthRegistry."""

from fastapi import APIRouter

from infrastructure.msgspec_fastapi import AppStruct, MsgSpecRoute
from infrastructure.service_health import service_health
from middleware import CurrentUserDep


class ServiceHealthItem(AppStruct):
    service: str
    capability: str
    severity: str
    message: str
    fallback: str | None = None
    degraded_seconds: int = 0


class SystemHealthResponse(AppStruct):
    degraded: list[ServiceHealthItem] = []


router = APIRouter(route_class=MsgSpecRoute, prefix="/system", tags=["system"])


@router.get("/health", response_model=SystemHealthResponse)
async def get_system_health(current_user: CurrentUserDep) -> SystemHealthResponse:
    entries = service_health.current()
    return SystemHealthResponse(
        degraded=[
            ServiceHealthItem(
                service=e.service,
                capability=e.capability,
                severity=e.severity,
                message=e.message,
                fallback=e.fallback,
                degraded_seconds=e.degraded_seconds,
            )
            for e in entries
        ]
    )
