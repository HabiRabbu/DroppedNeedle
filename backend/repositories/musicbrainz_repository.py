import asyncio
import logging
from typing import Optional

import httpx

from models.search import SearchResult
from services.preferences_service import PreferencesService
from infrastructure.cache.memory_cache import CacheInterface
from repositories.musicbrainz_base import mb_rate_limiter, set_mb_http_client, set_mb_api_base
from repositories.musicbrainz_artist import MusicBrainzArtistMixin
from repositories.musicbrainz_album import MusicBrainzAlbumMixin

logger = logging.getLogger(__name__)


class MusicBrainzRepository(MusicBrainzArtistMixin, MusicBrainzAlbumMixin):
    def __init__(self, http_client: httpx.AsyncClient, cache: CacheInterface, preferences_service: PreferencesService):
        self._cache = cache
        self._preferences_service = preferences_service
        set_mb_http_client(http_client)
        self._apply_settings()

    def _apply_settings(self) -> None:
        from api.v1.schemas.settings import (
            is_official_musicbrainz, _OFFICIAL_MB_RATE_LIMIT, _OFFICIAL_MB_CONCURRENT_SEARCHES,
        )

        settings = self._preferences_service.get_musicbrainz_connection()
        if is_official_musicbrainz(settings.api_url):
            settings.rate_limit = min(settings.rate_limit, _OFFICIAL_MB_RATE_LIMIT)
            settings.concurrent_searches = min(settings.concurrent_searches, _OFFICIAL_MB_CONCURRENT_SEARCHES)
        set_mb_api_base(settings.api_url)
        mb_rate_limiter.update_rate(settings.rate_limit)
        if mb_rate_limiter.capacity != settings.concurrent_searches:
            mb_rate_limiter.update_capacity(settings.concurrent_searches)

    async def search_grouped(
        self,
        query: str,
        limits: dict[str, int],
        buckets: Optional[list[str]] = None,
        included_secondary_types: Optional[set[str]] = None,
        included_primary_types: Optional[set[str]] = None
    ) -> dict[str, list[SearchResult]]:
        tasks = []
        task_keys = []

        if not buckets or "artists" in buckets:
            tasks.append(self.search_artists(query, limit=limits.get("artists", 10)))
            task_keys.append("artists")

        if not buckets or "albums" in buckets:
            tasks.append(self.search_albums(
                query,
                limit=limits.get("albums", 10),
                included_secondary_types=included_secondary_types,
                included_primary_types=included_primary_types
            ))
            task_keys.append("albums")

        if not tasks:
            return {}

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        results = {}
        for key, result in zip(task_keys, results_list):
            if isinstance(result, Exception):
                logger.error(f"Search {key} failed: {result}")
                results[key] = []
            else:
                results[key] = result

        return results
