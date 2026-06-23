"""AudioDB image pre-warming phase."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

import httpx

from repositories.protocols import CoverArtRepositoryProtocol
from repositories.coverart_disk_cache import get_cache_filename, VALID_IMAGE_CONTENT_TYPES
from services.cache_status_service import CacheStatusService
from infrastructure.queue.priority_queue import RequestPriority, get_priority_queue
from infrastructure.validators import validate_audiodb_image_url

if TYPE_CHECKING:
    from services.audiodb_image_service import AudioDBImageService

logger = logging.getLogger(__name__)

_AUDIODB_PREWARM_LOG_INTERVAL = 100


class AudioDBPhase:
    def __init__(
        self,
        cover_repo: CoverArtRepositoryProtocol,
        preferences_service: Any,
        audiodb_image_service: 'AudioDBImageService | None' = None,
    ):
        self._cover_repo = cover_repo
        self._preferences_service = preferences_service
        self._audiodb_image_service = audiodb_image_service

    _CACHE_CHECK_CHUNK = 200

    async def check_cache_needs(
        self,
        artists: list[dict],
        albums: list[Any],
    ) -> tuple[list[dict], list[Any]]:
        from infrastructure.validators import is_unknown_mbid
        svc = self._audiodb_image_service

        async def check_artist(artist: dict) -> dict | None:
            mbid = artist.get('mbid')
            if not mbid or is_unknown_mbid(mbid):
                return None
            cached = await svc.get_cached_artist_images(mbid)
            return None if cached is not None else artist

        async def check_album(album: Any) -> Any | None:
            mbid = getattr(album, 'musicbrainz_id', None) if hasattr(album, 'musicbrainz_id') else album.get('mbid') if isinstance(album, dict) else None
            if not mbid or is_unknown_mbid(mbid):
                return None
            cached = await svc.get_cached_album_images(mbid)
            return None if cached is not None else album

        needed_artists: list[dict] = []
        chunk = self._CACHE_CHECK_CHUNK
        for i in range(0, len(artists), chunk):
            results = await asyncio.gather(
                *(check_artist(a) for a in artists[i:i + chunk]), return_exceptions=True
            )
            needed_artists.extend(r for r in results if r is not None and not isinstance(r, Exception))

        needed_albums: list[Any] = []
        for i in range(0, len(albums), chunk):
            results = await asyncio.gather(
                *(check_album(a) for a in albums[i:i + chunk]), return_exceptions=True
            )
            needed_albums.extend(r for r in results if r is not None and not isinstance(r, Exception))

        return needed_artists, needed_albums

    async def download_bytes(self, url: str, entity_type: str, mbid: str) -> bool:
        try:
            if not validate_audiodb_image_url(url):
                logger.warning(
                    "audiodb.prewarm action=rejected_unsafe_url entity_type=%s mbid=%s",
                    entity_type, mbid[:8],
                )
                return False

            if entity_type == "artist":
                identifier = f"artist_{mbid}_500"
                suffix = "img"
            else:
                identifier = f"rg_{mbid}"
                suffix = "500"
            file_path = self._cover_repo.cache_dir / f"{get_cache_filename(identifier, suffix)}.bin"
            if file_path.exists():
                return True

            priority_mgr = get_priority_queue()
            semaphore = await priority_mgr.acquire_slot(RequestPriority.BACKGROUND_SYNC)
            http_client = getattr(self._cover_repo, '_client', None)
            async with semaphore:
                if http_client is not None:
                    response = await http_client.get(url, follow_redirects=True)
                else:
                    logger.debug("audiodb.prewarm action=http_client_fallback entity_type=%s mbid=%s", entity_type, mbid[:8])
                    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
                        response = await client.get(url, headers={"User-Agent": "DroppedNeedle/1.0"}, follow_redirects=True)

            if response.status_code != 200:
                logger.debug(
                    "audiodb.prewarm action=byte_download_failed entity_type=%s mbid=%s status=%d",
                    entity_type, mbid[:8], response.status_code,
                )
                return False

            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type not in VALID_IMAGE_CONTENT_TYPES:
                logger.debug(
                    "audiodb.prewarm action=byte_download_invalid_type entity_type=%s mbid=%s content_type=%s",
                    entity_type, mbid[:8], content_type,
                )
                return False

            _MAX_IMAGE_BYTES = 20 * 1024 * 1024
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > _MAX_IMAGE_BYTES:
                logger.warning(
                    "audiodb.prewarm action=byte_download_too_large entity_type=%s mbid=%s size=%s",
                    entity_type, mbid[:8], content_length,
                )
                return False
            if len(response.content) > _MAX_IMAGE_BYTES:
                logger.warning(
                    "audiodb.prewarm action=byte_download_too_large entity_type=%s mbid=%s size=%d",
                    entity_type, mbid[:8], len(response.content),
                )
                return False

            disk_cache = getattr(self._cover_repo, '_disk_cache', None)
            if disk_cache is None:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                import aiofiles
                async with aiofiles.open(file_path, 'wb') as f:
                    await f.write(response.content)
                return True

            await disk_cache.write(
                file_path, response.content, content_type,
                extra_meta={"source": "audiodb"},
                is_monitored=True,
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "audiodb.prewarm action=byte_download_error entity_type=%s mbid=%s error=%s",
                entity_type, mbid[:8], e,
            )
            return False

    def sort_by_cover_priority(self, items: list, entity_type: str) -> list:
        def has_cover(item: Any) -> bool:
            if entity_type == "artist":
                mbid = item.get('mbid') if isinstance(item, dict) else None
                if not mbid:
                    return True
                identifier = f"artist_{mbid}_500"
                suffix = "img"
            else:
                mbid = getattr(item, 'musicbrainz_id', None) if hasattr(item, 'musicbrainz_id') else item.get('mbid') if isinstance(item, dict) else None
                if not mbid:
                    return True
                identifier = f"rg_{mbid}"
                suffix = "500"
            file_path = self._cover_repo.cache_dir / f"{get_cache_filename(identifier, suffix)}.bin"
            return file_path.exists()

        return sorted(items, key=has_cover)

    async def precache_audiodb_data(
        self,
        artists: list[dict],
        albums: list[Any],
        status_service: CacheStatusService,
        generation: int = 0,
    ) -> None:
        if self._audiodb_image_service is None:
            await status_service.skip_phase('audiodb_prewarm', generation=generation)
            return

        settings = self._preferences_service.get_advanced_settings()
        if not settings.audiodb_enabled:
            await status_service.skip_phase('audiodb_prewarm', generation=generation)
            return

        concurrency = settings.audiodb_prewarm_concurrency
        inter_item_delay = settings.audiodb_prewarm_delay

        needed_artists, needed_albums = await self.check_cache_needs(artists, albums)
        total = len(needed_artists) + len(needed_albums)
        if total == 0:
            await status_service.skip_phase('audiodb_prewarm', generation=generation)
            return

        await status_service.update_phase('audiodb_prewarm', total, generation=generation)

        needed_artists = self.sort_by_cover_priority(needed_artists, "artist")
        needed_albums = self.sort_by_cover_priority(needed_albums, "album")

        processed = 0
        bytes_ok = 0
        bytes_fail = 0
        svc = self._audiodb_image_service
        sem = asyncio.Semaphore(concurrency)
        counter_lock = asyncio.Lock()

        async def process_artist(artist: dict) -> None:
            nonlocal processed, bytes_ok, bytes_fail
            if status_service.is_cancelled():
                return
            if not self._preferences_service.get_advanced_settings().audiodb_enabled:
                return

            mbid = artist.get('mbid')
            name = artist.get('name', 'Unknown')

            async with sem:
                if inter_item_delay > 0:
                    await asyncio.sleep(inter_item_delay)
                try:
                    result = await svc.fetch_and_cache_artist_images(mbid, name, is_monitored=True)
                except Exception as e:  # noqa: BLE001
                    result = None
                    logger.warning("audiodb.prewarm action=artist_error mbid=%s error=%s", mbid[:8] if mbid else '?', e)

            if result and not result.is_negative and result.thumb_url:
                ok = await self.download_bytes(result.thumb_url, "artist", mbid)
                async with counter_lock:
                    if ok:
                        bytes_ok += 1
                    else:
                        bytes_fail += 1

            async with counter_lock:
                processed += 1
                local_processed = processed
            await status_service.update_progress(local_processed, f"AudioDB: {name}", generation=generation)

        async def process_album(album: Any) -> None:
            nonlocal processed, bytes_ok, bytes_fail
            if status_service.is_cancelled():
                return
            if not self._preferences_service.get_advanced_settings().audiodb_enabled:
                return

            mbid = getattr(album, 'musicbrainz_id', None) if hasattr(album, 'musicbrainz_id') else album.get('mbid') if isinstance(album, dict) else None
            artist_name = getattr(album, 'artist_name', None) if hasattr(album, 'artist_name') else album.get('artist_name') if isinstance(album, dict) else None
            album_name = getattr(album, 'title', None) if hasattr(album, 'title') else album.get('title') if isinstance(album, dict) else None

            async with sem:
                if inter_item_delay > 0:
                    await asyncio.sleep(inter_item_delay)
                try:
                    result = await svc.fetch_and_cache_album_images(
                        mbid, artist_name=artist_name, album_name=album_name, is_monitored=True,
                    )
                except Exception as e:  # noqa: BLE001
                    result = None
                    logger.warning("audiodb.prewarm action=album_error mbid=%s error=%s", mbid[:8] if mbid else '?', e)

            if result and not result.is_negative and result.album_thumb_url:
                ok = await self.download_bytes(result.album_thumb_url, "album", mbid)
                async with counter_lock:
                    if ok:
                        bytes_ok += 1
                    else:
                        bytes_fail += 1

            async with counter_lock:
                processed += 1
                local_processed = processed
            await status_service.update_progress(local_processed, f"AudioDB: {album_name or 'Unknown'}", generation=generation)

        chunk = max(concurrency * 4, 20)
        for i in range(0, len(needed_artists), chunk):
            if status_service.is_cancelled():
                break
            batch = needed_artists[i:i + chunk]
            await asyncio.gather(*(process_artist(a) for a in batch), return_exceptions=True)

        for i in range(0, len(needed_albums), chunk):
            if status_service.is_cancelled():
                break
            batch = needed_albums[i:i + chunk]
            await asyncio.gather(*(process_album(a) for a in batch), return_exceptions=True)
