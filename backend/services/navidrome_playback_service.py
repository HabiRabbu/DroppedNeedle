from __future__ import annotations

import logging
import time
from collections import OrderedDict

from fastapi.responses import Response, StreamingResponse

from infrastructure.cache.memory_cache import CacheInterface
from repositories.navidrome_models import StreamProxyResult
from repositories.protocols import NavidromeRepositoryProtocol
from services.per_user_client_factory import PerUserClientFactory

logger = logging.getLogger(__name__)

_MAX_TRACKED_PLAYBACKS = 256
_playback_start_times: OrderedDict[str, float] = OrderedDict()


class NavidromePlaybackService:
    def __init__(
        self,
        navidrome_repo: NavidromeRepositoryProtocol,
        cache: CacheInterface | None = None,
        client_factory: PerUserClientFactory | None = None,
    ) -> None:
        self._navidrome = navidrome_repo
        self._cache = cache
        self._client_factory = client_factory

    async def _repo_for(self, user_id: str | None) -> NavidromeRepositoryProtocol:
        """The user's own Navidrome client when linked, else the app-level one.

        Fallback covers only "not linked" - an auth failure on a linked account
        fails the attribution call (fail closed) rather than silently
        misattributing it to the app account.
        """
        if user_id and self._client_factory:
            per_user = await self._client_factory.resolve_navidrome(user_id)
            if per_user is not None:
                return per_user
        return self._navidrome

    def get_stream_url(self, song_id: str) -> str:
        return self._navidrome.build_stream_url(song_id)

    async def proxy_head(self, item_id: str) -> Response:
        """Proxy a HEAD request to Navidrome and return a FastAPI Response."""
        result: StreamProxyResult = await self._navidrome.proxy_head_stream(item_id)
        return Response(status_code=200, headers=result.headers)

    async def proxy_stream(
        self, item_id: str, range_header: str | None = None
    ) -> StreamingResponse:
        """Proxy a GET stream from Navidrome and return a FastAPI StreamingResponse."""
        result: StreamProxyResult = await self._navidrome.proxy_get_stream(
            item_id, range_header=range_header
        )
        return StreamingResponse(
            content=result.body_chunks,
            status_code=result.status_code,
            headers=result.headers,
            media_type=result.media_type,
        )

    async def scrobble(self, song_id: str, user_id: str | None = None) -> bool:
        time_ms = int(time.time() * 1000)
        try:
            repo = await self._repo_for(user_id)
            ok = await repo.scrobble(song_id, time_ms=time_ms)
            _playback_start_times.pop(song_id, None)
            if self._cache:
                await self._cache.delete("navidrome:now_playing")
            return ok
        except Exception:  # noqa: BLE001
            logger.warning("Navidrome scrobble failed for %s", song_id, exc_info=True)
            return False

    async def report_now_playing(self, song_id: str, user_id: str | None = None) -> bool:
        try:
            repo = await self._repo_for(user_id)
            ok = await repo.now_playing(song_id)
            _playback_start_times[song_id] = time.time()
            _playback_start_times.move_to_end(song_id)
            while len(_playback_start_times) > _MAX_TRACKED_PLAYBACKS:
                _playback_start_times.popitem(last=False)
            if self._cache:
                await self._cache.delete("navidrome:now_playing")
            return ok
        except Exception:  # noqa: BLE001
            logger.warning("Navidrome now-playing failed for %s", song_id, exc_info=True)
            return False

    async def clear_now_playing(self, song_id: str) -> None:
        """Stop tracking estimated position for a song (player closed/paused)."""
        _playback_start_times.pop(song_id, None)
        if self._cache:
            await self._cache.delete("navidrome:now_playing")

    @staticmethod
    def get_estimated_position(song_id: str) -> float | None:
        started = _playback_start_times.get(song_id)
        if started is None:
            return None
        return time.time() - started
