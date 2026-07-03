from fastapi import APIRouter, Depends, Query

from api.v1.schemas.discovery_batches import (
    DiscoveryBatchCreate,
    DiscoveryBatchDetail,
    DiscoveryBatchListResponse,
    DiscoveryBatchRemoveResult,
)
from core.dependencies import get_discovery_batch_service
from core.dependencies.type_aliases import CurrentUserDep
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from services.discovery_batch_service import DiscoveryBatchService

router = APIRouter(route_class=MsgSpecRoute, prefix="/discover/batches", tags=["discover"])


@router.post("", response_model=DiscoveryBatchDetail, status_code=202)
async def create_batch(
    current_user: CurrentUserDep,
    body: DiscoveryBatchCreate = MsgSpecBody(DiscoveryBatchCreate),
    service: DiscoveryBatchService = Depends(get_discovery_batch_service),
) -> DiscoveryBatchDetail:
    return await service.create(
        current_user.id, current_user.role, current_user.display_name, body
    )


@router.get("", response_model=DiscoveryBatchListResponse)
async def list_batches(
    current_user: CurrentUserDep,
    service: DiscoveryBatchService = Depends(get_discovery_batch_service),
) -> DiscoveryBatchListResponse:
    return DiscoveryBatchListResponse(batches=await service.list_for_user(current_user.id))


@router.get("/{batch_id}", response_model=DiscoveryBatchDetail)
async def get_batch(
    current_user: CurrentUserDep,
    batch_id: str,
    service: DiscoveryBatchService = Depends(get_discovery_batch_service),
) -> DiscoveryBatchDetail:
    return await service.get_detail(current_user.id, current_user.role, batch_id)


@router.delete("/{batch_id}", response_model=DiscoveryBatchRemoveResult)
async def remove_batch(
    current_user: CurrentUserDep,
    batch_id: str,
    remove_albums: bool = Query(default=True, description="Also remove/cancel this batch's albums"),
    service: DiscoveryBatchService = Depends(get_discovery_batch_service),
) -> DiscoveryBatchRemoveResult:
    return await service.remove(current_user.id, current_user.role, batch_id, remove_albums)
