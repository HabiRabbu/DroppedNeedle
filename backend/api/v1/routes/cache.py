from fastapi import APIRouter, Depends, HTTPException

from api.v1.schemas.cache import CacheStats, CacheClearResponse
from core.dependencies import get_cache_service
from infrastructure.msgspec_fastapi import MsgSpecRoute
from middleware import CurrentAdminDep
from services.cache_service import CacheService

router = APIRouter(route_class=MsgSpecRoute, prefix="/cache", tags=["cache"])


@router.get("/stats", response_model=CacheStats)
async def get_cache_stats(
    cache_service: CacheService = Depends(get_cache_service),
):
    return await cache_service.get_stats()


@router.post("/clear/memory", response_model=CacheClearResponse)
async def clear_memory_cache(
    _: CurrentAdminDep,
    cache_service: CacheService = Depends(get_cache_service),
):
    result = await cache_service.clear_memory_cache()
    if not result.success:
        raise HTTPException(status_code=500, detail=result.message)
    return result


@router.post("/clear/disk", response_model=CacheClearResponse)
async def clear_disk_cache(
    _: CurrentAdminDep,
    cache_service: CacheService = Depends(get_cache_service),
):
    result = await cache_service.clear_disk_cache()
    if not result.success:
        raise HTTPException(status_code=500, detail=result.message)
    return result


@router.post("/clear/all", response_model=CacheClearResponse)
async def clear_all_cache(
    _: CurrentAdminDep,
    cache_service: CacheService = Depends(get_cache_service),
):
    result = await cache_service.clear_all_cache()
    if not result.success:
        raise HTTPException(status_code=500, detail=result.message)
    return result


@router.post("/clear/covers", response_model=CacheClearResponse)
async def clear_covers_cache(
    _: CurrentAdminDep,
    cache_service: CacheService = Depends(get_cache_service),
):
    result = await cache_service.clear_covers_cache()
    if not result.success:
        raise HTTPException(status_code=500, detail=result.message)
    return result


@router.post("/clear/library", response_model=CacheClearResponse)
async def clear_library_cache(
    _: CurrentAdminDep,
    cache_service: CacheService = Depends(get_cache_service),
):
    result = await cache_service.clear_library_cache()
    if not result.success:
        raise HTTPException(status_code=500, detail=result.message)
    return result


@router.post("/clear/audiodb", response_model=CacheClearResponse)
async def clear_audiodb_cache(
    _: CurrentAdminDep,
    cache_service: CacheService = Depends(get_cache_service),
):
    result = await cache_service.clear_audiodb()
    if not result.success:
        raise HTTPException(status_code=500, detail=result.message)
    return result
