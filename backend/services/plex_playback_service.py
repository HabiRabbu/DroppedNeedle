from __future__ import annotations

import logging

from fastapi.responses import Response, StreamingResponse

from infrastructure.cache.memory_cache import CacheInterface
from repositories.plex_models import StreamProxyResult
from repositories.protocols.plex import PlexRepositoryProtocol
from services.per_user_client_factory import PerUserClientFactory

logger = logging.getLogger(__name__)


class PlexPlaybackService:
    def __init__(
        self,
        plex_repo: PlexRepositoryProtocol,
        cache: CacheInterface | None = None,
        client_factory: PerUserClientFactory | None = None,
    ) -> None:
        self._plex = plex_repo
        self._cache = cache
        self._client_factory = client_factory

    async def _repo_for(self, user_id: str | None) -> PlexRepositoryProtocol:
        """The user's own Plex client when linked, else the app-level one.

        Fallback covers only "not linked" - an auth failure on a linked account
        fails the attribution call (fail closed) rather than silently
        misattributing it to the app account.
        """
        if user_id and self._client_factory:
            per_user = await self._client_factory.resolve_plex(user_id)
            if per_user is not None:
                return per_user
        return self._plex

    async def proxy_head(self, part_key: str) -> Response:
        result: StreamProxyResult = await self._plex.proxy_head_stream(part_key)
        return Response(status_code=result.status_code, headers=result.headers)

    async def proxy_stream(
        self, part_key: str, range_header: str | None = None
    ) -> StreamingResponse:
        result: StreamProxyResult = await self._plex.proxy_get_stream(
            part_key, range_header=range_header
        )
        return StreamingResponse(
            content=result.body_chunks,
            status_code=result.status_code,
            headers=result.headers,
            media_type=result.media_type,
        )

    async def scrobble(self, rating_key: str, user_id: str | None = None) -> bool:
        try:
            repo = await self._repo_for(user_id)
            ok = await repo.scrobble(rating_key)
            if self._cache:
                await self._cache.delete("plex:sessions")
            return ok
        except Exception:  # noqa: BLE001
            logger.warning("Plex scrobble failed for %s", rating_key, exc_info=True)
            return False

    async def report_now_playing(self, rating_key: str, user_id: str | None = None) -> bool:
        try:
            repo = await self._repo_for(user_id)
            ok = await repo.now_playing(rating_key)
            if self._cache:
                await self._cache.delete("plex:sessions")
            return ok
        except Exception:  # noqa: BLE001
            logger.warning("Plex now-playing failed for %s", rating_key, exc_info=True)
            return False

    async def report_stopped(self, rating_key: str, user_id: str | None = None) -> bool:
        try:
            repo = await self._repo_for(user_id)
            ok = await repo.now_playing(rating_key, state="stopped")
            if self._cache:
                await self._cache.delete("plex:sessions")
            return ok
        except Exception:  # noqa: BLE001
            logger.warning("Plex stopped report failed for %s", rating_key, exc_info=True)
            return False

    async def proxy_thumb(self, rating_key: str, size: int = 500) -> tuple[bytes, str]:
        return await self._plex.proxy_thumb(rating_key, size=size)
