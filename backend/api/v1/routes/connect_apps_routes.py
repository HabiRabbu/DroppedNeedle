"""Connect Apps management.

settings GET is authenticated, PUT is admin-only. App-passwords are per-user
self-service (secret shown once); no secret column is ever serialized out.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.v1.schemas.connect_apps import (
    AppPasswordCreateRequest,
    AppPasswordCreateResponse,
    AppPasswordListResponse,
)
from api.v1.schemas.settings import ConnectAppsSettings
from core.dependencies import get_app_password_service, get_preferences_service
from core.exceptions import ConfigurationError, ConflictError, PermissionDeniedError
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from middleware import CurrentAdminDep, CurrentUserDep
from services.compat.app_password_service import (
    MAX_ACTIVE_APP_PASSWORDS,
    AppPasswordView,
)

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/connect-apps", tags=["connect-apps"])


@router.get("/settings", response_model=ConnectAppsSettings)
async def get_connect_apps_settings(
    _: CurrentUserDep,  # any signed-in user may read (drives read-only view + URLs)
    preferences=Depends(get_preferences_service),
) -> ConnectAppsSettings:
    return preferences.get_connect_apps_settings()


@router.put("/settings", response_model=ConnectAppsSettings)
async def update_connect_apps_settings(
    _: CurrentAdminDep,  # only an admin may write
    settings: ConnectAppsSettings = MsgSpecBody(ConnectAppsSettings),
    preferences=Depends(get_preferences_service),
) -> ConnectAppsSettings:
    try:
        preferences.save_connect_apps_settings(settings)
        return preferences.get_connect_apps_settings()
    except ConfigurationError as e:
        logger.warning("Configuration error updating connect-apps settings: %s", e)
        raise HTTPException(status_code=400, detail="Connect Apps settings are invalid")


@router.get("/app-passwords", response_model=AppPasswordListResponse)
async def list_app_passwords(
    current_user: CurrentUserDep,
    service=Depends(get_app_password_service),
) -> AppPasswordListResponse:
    items = await service.list_for_user(current_user.id)
    return AppPasswordListResponse(
        cap=MAX_ACTIVE_APP_PASSWORDS, active_count=len(items), items=items
    )


@router.post("/app-passwords", response_model=AppPasswordCreateResponse)
async def create_app_password(
    current_user: CurrentUserDep,
    body: AppPasswordCreateRequest = MsgSpecBody(AppPasswordCreateRequest),
    service=Depends(get_app_password_service),
) -> AppPasswordCreateResponse:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="A name is required")
    try:
        record, secret = await service.create(current_user.id, name)
    except ConflictError:  # cap reached
        raise HTTPException(
            status_code=409,
            detail=f"App-password limit reached ({MAX_ACTIVE_APP_PASSWORDS}). "
            "Revoke one before creating a new one.",
        )
    # secret returned exactly once; never stored in plaintext, never re-fetchable
    return AppPasswordCreateResponse(
        secret=secret,
        app_password=AppPasswordView(
            id=record.id, name=record.name, created_at=record.created_at,
            last_used_at=record.last_used_at, last_client=record.last_client,
        ),
    )


@router.delete("/app-passwords/{app_password_id}", status_code=204)
async def revoke_app_password(
    current_user: CurrentUserDep,
    app_password_id: str,
    service=Depends(get_app_password_service),
) -> None:
    try:
        await service.revoke(current_user.id, app_password_id)
    except PermissionDeniedError:
        # 404 (not 403) avoids leaking the id
        raise HTTPException(status_code=404, detail="App-password not found")
