"""Authenticated per-user outbound Navidrome catalog preferences."""

from fastapi import APIRouter, Depends, HTTPException

from api.v1.schemas.navidrome import (
    NavidromeFolderPreferenceResponse,
    NavidromeFolderPreferenceUpdate,
    NavidromeMusicFolder,
)
from core.dependencies import CurrentUserDep, get_navidrome_folder_scope_service
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from services.navidrome_folder_scope_service import (
    NavidromeFolderResolution,
    NavidromeFolderScopeService,
)

router = APIRouter(
    route_class=MsgSpecRoute,
    prefix="/me/navidrome/music-folder-preferences",
    tags=["profile"],
)


def _response(resolution: NavidromeFolderResolution) -> NavidromeFolderPreferenceResponse:
    return NavidromeFolderPreferenceResponse(
        mode=resolution.preference.mode,
        selected_folder_ids=list(resolution.preference.selected_folder_ids),
        available_folders=[
            NavidromeMusicFolder(id=folder_id, name=name)
            for folder_id, name in resolution.available_folders
        ],
        stale_folder_ids=list(resolution.stale_folder_ids),
        source_available=resolution.source_available,
        scope_revision=resolution.scope.cache_segment,
    )


@router.get("", response_model=NavidromeFolderPreferenceResponse)
async def get_music_folder_preferences(
    current_user: CurrentUserDep,
    service: NavidromeFolderScopeService = Depends(
        get_navidrome_folder_scope_service
    ),
) -> NavidromeFolderPreferenceResponse:
    return _response(await service.resolve(current_user.id))


@router.put("", response_model=NavidromeFolderPreferenceResponse)
async def update_music_folder_preferences(
    current_user: CurrentUserDep,
    body: NavidromeFolderPreferenceUpdate = MsgSpecBody(
        NavidromeFolderPreferenceUpdate
    ),
    service: NavidromeFolderScopeService = Depends(
        get_navidrome_folder_scope_service
    ),
) -> NavidromeFolderPreferenceResponse:
    try:
        resolution = await service.save(
            current_user.id,
            mode=body.mode,
            selected_folder_ids=body.selected_folder_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _response(resolution)
