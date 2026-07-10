"""Free Music routes (D24) - DroppedNeedle's own lawful download client.

Reading your own downloads is a user surface; cancelling and retrying are
curator actions, matching the rest of the download queue.
"""

import logging

from fastapi import APIRouter, Depends

from api.v1.schemas.free_music import (
    FreeMusicTaskResponse,
    FreeMusicTasksResponse,
    task_to_response,
)
from core.dependencies import get_free_music_service
from infrastructure.msgspec_fastapi import MsgSpecRoute
from middleware import CurrentCuratorDep, CurrentUserDep

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/free-music", tags=["free-music"])


@router.get("/tasks", response_model=FreeMusicTasksResponse)
async def list_tasks(
    current_user: CurrentUserDep,
    all: bool = False,  # noqa: A002 - query-param name is the API surface
    service=Depends(get_free_music_service),
):
    """Your downloads; admins may pass ``all=true`` for everyone's."""
    include_all = all and current_user.role == "admin"
    tasks = await service.list_tasks(user_id=current_user.id, include_all=include_all)
    return FreeMusicTasksResponse(tasks=[task_to_response(t) for t in tasks])


@router.get("/tasks/{task_id}", response_model=FreeMusicTaskResponse)
async def get_task(
    task_id: str,
    current_user: CurrentUserDep,
    service=Depends(get_free_music_service),
):
    task = await service.get_task(
        task_id, user_id=current_user.id, is_admin=current_user.role == "admin"
    )
    return task_to_response(task)


@router.post("/tasks/{task_id}/cancel", response_model=FreeMusicTaskResponse)
async def cancel_task(
    task_id: str,
    current_user: CurrentCuratorDep,
    service=Depends(get_free_music_service),
):
    task = await service.cancel(
        task_id, user_id=current_user.id, is_admin=current_user.role == "admin"
    )
    return task_to_response(task)


@router.post("/tasks/{task_id}/retry", response_model=FreeMusicTaskResponse)
async def retry_task(
    task_id: str,
    current_user: CurrentCuratorDep,
    service=Depends(get_free_music_service),
):
    task = await service.retry(
        task_id, user_id=current_user.id, is_admin=current_user.role == "admin"
    )
    return task_to_response(task)
