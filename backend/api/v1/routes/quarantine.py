"""Admin-only download-quarantine routes (Phase 6): list and delete entries."""

import logging

import msgspec
from fastapi import APIRouter, Depends, Query

from api.v1.schemas.download import OperationResult, QuarantineEntry, QuarantineListResponse
from core.dependencies import get_download_store
from infrastructure.msgspec_fastapi import MsgSpecRoute
from middleware import CurrentAdminDep

logger = logging.getLogger(__name__)


async def _admin_guard(_: CurrentAdminDep) -> None:
    ...


router = APIRouter(
    route_class=MsgSpecRoute,
    prefix="/downloads",
    tags=["quarantine"],
    dependencies=[Depends(_admin_guard)],
)


@router.get("/quarantine", response_model=QuarantineListResponse)
async def list_quarantine(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    store=Depends(get_download_store),
):
    rows = await store.list_quarantine(page, page_size)
    items = [msgspec.convert(row, type=QuarantineEntry, strict=False) for row in rows]
    return QuarantineListResponse(items=items, page=page)


@router.delete("/quarantine/{quarantine_id}", response_model=OperationResult)
async def delete_quarantine(quarantine_id: int, store=Depends(get_download_store)):
    await store.delete_quarantine(quarantine_id)
    return OperationResult(success=True)
