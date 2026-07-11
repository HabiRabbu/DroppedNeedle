import logging

import httpx
from fastapi.responses import Response, StreamingResponse

from core.exceptions import ExternalServiceError, JellyfinAuthError, PlaybackNotAllowedError
from infrastructure.constants import JELLYFIN_TICKS_PER_SECOND
from infrastructure.cache.memory_cache import CacheInterface
from repositories.navidrome_models import StreamProxyResult
from repositories.protocols import JellyfinRepositoryProtocol
from services.per_user_client_factory import PerUserClientFactory

logger = logging.getLogger(__name__)


class JellyfinPlaybackService:
    def __init__(
        self,
        jellyfin_repo: JellyfinRepositoryProtocol,
        cache: CacheInterface | None = None,
        client_factory: PerUserClientFactory | None = None,
    ):
        self._jellyfin = jellyfin_repo
        self._cache = cache
        self._client_factory = client_factory

    async def _repo_for(self, user_id: str | None) -> JellyfinRepositoryProtocol:
        """The user's own Jellyfin client when linked, else the app-level one.

        Fallback covers only "not linked" - an auth failure on a linked account
        fails the attribution call (fail closed) rather than silently
        misattributing it to the app account.
        """
        if user_id and self._client_factory:
            per_user = await self._client_factory.resolve_jellyfin(user_id)
            if per_user is not None:
                return per_user
        return self._jellyfin

    async def _invalidate_sessions_cache(self, repo: JellyfinRepositoryProtocol) -> None:
        if not self._cache:
            return
        uid = getattr(repo, '_user_id', None) or 'default'
        await self._cache.delete(f"jellyfin:sessions:{uid}")

    async def start_playback(
        self,
        item_id: str,
        play_session_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Report playback start to Jellyfin. Returns play_session_id.

        Handles nullable PlaySessionId and checks for ErrorCode in the
        PlaybackInfoResponse (NotAllowed, NoCompatibleStream, RateLimitExceeded).
        """
        repo = await self._repo_for(user_id)
        resolved_play_session_id = play_session_id
        play_method = "DirectPlay"

        if not resolved_play_session_id:
            try:
                info = await repo.get_playback_info(item_id)
            except JellyfinAuthError:
                if repo is self._jellyfin:
                    raise
                # linked account's token was revoked: stream without session
                # reporting instead of failing the request (the stream itself
                # rides the app-level account, D2)
                logger.warning(
                    "Per-user Jellyfin token rejected for user %s, "
                    "streaming %s without session reporting",
                    user_id,
                    item_id,
                )
                return ""

            error_code = info.get("ErrorCode")
            if error_code:
                raise PlaybackNotAllowedError(
                    f"Jellyfin playback not allowed: {error_code}"
                )

            resolved_play_session_id = info.get("PlaySessionId")
            if not resolved_play_session_id:
                logger.warning(
                    "Jellyfin returned null PlaySessionId for item %s, "
                    "streaming without session reporting",
                    item_id,
                )
                return ""

            media_sources = info.get("MediaSources") or []
            if media_sources:
                src = media_sources[0]
                if src.get("SupportsDirectPlay"):
                    play_method = "DirectPlay"
                elif src.get("SupportsDirectStream"):
                    play_method = "DirectStream"
                elif src.get("TranscodingUrl"):
                    play_method = "Transcode"

        try:
            await repo.report_playback_start(
                item_id, resolved_play_session_id, play_method=play_method
            )
            await self._invalidate_sessions_cache(repo)
        except (httpx.HTTPError, ExternalServiceError) as e:
            logger.error(
                "Failed to report playback start for %s: %s", item_id, e
            )

        return resolved_play_session_id

    async def report_progress(
        self,
        item_id: str,
        play_session_id: str,
        position_seconds: float,
        is_paused: bool,
        user_id: str | None = None,
    ) -> None:
        if not play_session_id:
            return
        position_ticks = int(position_seconds * JELLYFIN_TICKS_PER_SECOND)
        try:
            repo = await self._repo_for(user_id)
            await repo.report_playback_progress(
                item_id, play_session_id, position_ticks, is_paused
            )
            await self._invalidate_sessions_cache(repo)
        except (httpx.HTTPError, ExternalServiceError) as e:
            logger.warning("Progress report failed for %s: %s", item_id, e)

    async def stop_playback(
        self,
        item_id: str,
        play_session_id: str,
        position_seconds: float,
        user_id: str | None = None,
    ) -> None:
        if not play_session_id:
            return
        position_ticks = int(position_seconds * JELLYFIN_TICKS_PER_SECOND)
        try:
            repo = await self._repo_for(user_id)
            await repo.report_playback_stopped(
                item_id, play_session_id, position_ticks
            )
            await self._invalidate_sessions_cache(repo)
        except (httpx.HTTPError, ExternalServiceError) as e:
            logger.warning("Stop report failed for %s: %s", item_id, e)

    async def proxy_head(self, item_id: str) -> Response:
        result: StreamProxyResult = await self._jellyfin.proxy_head_stream(item_id)
        return Response(status_code=200, headers=result.headers)

    async def proxy_stream(
        self, item_id: str, range_header: str | None = None
    ) -> StreamingResponse:
        result: StreamProxyResult = await self._jellyfin.proxy_get_stream(
            item_id, range_header=range_header
        )
        return StreamingResponse(
            content=result.body_chunks,
            status_code=result.status_code,
            headers=result.headers,
            media_type=result.media_type,
        )
