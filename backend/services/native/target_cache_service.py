"""Target-safe semantics for the shared cache administration surface."""

from api.v1.schemas.cache import CacheClearResponse
from infrastructure.cache.cache_keys import (
    library_identification_prefixes,
    library_policy_prefixes,
)
from services.cache_service import CacheService


class TargetCacheService(CacheService):
    async def clear_library_cache(self) -> CacheClearResponse:
        cleared = 0
        for prefix in [
            *library_identification_prefixes(),
            *library_policy_prefixes(),
        ]:
            cleared += await self._cache.clear_prefix(prefix)
        self._cached_stats = None
        return CacheClearResponse(
            success=True,
            message=(
                f"Cleared {cleared} library cache entries. "
                "The native catalog and rollback data were preserved."
            ),
            cleared_memory_entries=cleared,
            cleared_disk_files=0,
        )
