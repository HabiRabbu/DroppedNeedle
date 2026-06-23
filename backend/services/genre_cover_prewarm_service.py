from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from infrastructure.queue.priority_queue import RequestPriority

if TYPE_CHECKING:
    from repositories.coverart_repository import CoverArtRepository

logger = logging.getLogger(__name__)

_PREWARM_INTER_ITEM_DELAY = 2.0
_MAX_CONCURRENT_PREWARMS = 3
_MAX_MBIDS_PER_RUN = 100


class GenreCoverPrewarmService:
    def __init__(self, cover_repo: CoverArtRepository) -> None:
        self._cover_repo = cover_repo
        self._active_genres: dict[str, asyncio.Task[None]] = {}
        self._global_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PREWARMS)

    def schedule_prewarm(
        self,
        genre_name: str,
        artist_mbids: list[str],
        album_mbids: list[str],
    ) -> None:
        existing = self._active_genres.get(genre_name)
        if existing is not None and not existing.done():
            logger.debug("Pre-warm already in progress for genre '%s', skipping", genre_name)
            return

        task = asyncio.create_task(
            self._prewarm(genre_name, artist_mbids, album_mbids),
            name=f"genre-prewarm-{genre_name}",
        )
        self._active_genres[genre_name] = task
        from core.task_registry import TaskRegistry
        try:
            TaskRegistry.get_instance().register(f"genre-prewarm-{genre_name}", task)
        except RuntimeError:
            pass
        task.add_done_callback(
            lambda _t, _g=genre_name, _ref=task: (
                self._active_genres.pop(_g, None)
                if self._active_genres.get(_g) is _ref
                else None
            )
        )

    async def shutdown(self) -> None:
        tasks = list(self._active_genres.values())
        if not tasks:
            return
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._active_genres.clear()

    async def _prewarm(
        self,
        genre_name: str,
        artist_mbids: list[str],
        album_mbids: list[str],
    ) -> None:
        async with self._global_semaphore:
            all_artist = artist_mbids[:_MAX_MBIDS_PER_RUN]
            remaining = _MAX_MBIDS_PER_RUN - len(all_artist)
            all_album = album_mbids[:remaining] if remaining > 0 else []
            warmed = 0
            try:
                for i, mbid in enumerate(all_artist):
                    try:
                        await self._cover_repo.get_artist_image(
                            mbid, size=250, priority=RequestPriority.BACKGROUND_SYNC
                        )
                        warmed += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("Pre-warm artist image failed for %s: %s", mbid[:8], exc)
                    if i < len(all_artist) - 1 or all_album:
                        await asyncio.sleep(_PREWARM_INTER_ITEM_DELAY)

                for i, mbid in enumerate(all_album):
                    try:
                        await self._cover_repo.get_release_group_cover(
                            mbid, size="250", priority=RequestPriority.BACKGROUND_SYNC
                        )
                        warmed += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("Pre-warm album cover failed for %s: %s", mbid[:8], exc)
                    if i < len(all_album) - 1:
                        await asyncio.sleep(_PREWARM_INTER_ITEM_DELAY)

            except Exception as exc:  # noqa: BLE001
                logger.error("Genre cover pre-warm failed for '%s': %s", genre_name, exc)
