"""Genre artist resolution and image enrichment."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from infrastructure.cache.cache_keys import GENRE_ARTIST_PREFIX, GENRE_SECTION_PREFIX
from infrastructure.cache.memory_cache import CacheInterface
from repositories.protocols import MusicBrainzRepositoryProtocol

logger = logging.getLogger(__name__)

VARIOUS_ARTISTS_MBID = "89ad4ac3-39f7-470e-963a-56509c546377"
GENRE_CACHE_TTL = 24 * 60 * 60
GENRE_SECTION_TTL_DEFAULT = 6 * 60 * 60


class GenreService:
    def __init__(
        self,
        musicbrainz_repo: MusicBrainzRepositoryProtocol,
        memory_cache: CacheInterface | None = None,
        audiodb_image_service: Any = None,
        cache_dir: Path | None = None,
        preferences_service: Any = None,
    ):
        self._mb_repo = musicbrainz_repo
        self._memory_cache = memory_cache
        self._audiodb_image_service = audiodb_image_service
        self._preferences_service = preferences_service
        self._genre_build_locks: dict[str, asyncio.Lock] = {}

        self._genre_section_dir: Path | None = None
        if cache_dir:
            self._genre_section_dir = cache_dir / "genre_sections"
            self._genre_section_dir.mkdir(parents=True, exist_ok=True)

    def _get_genre_section_ttl(self) -> int:
        if self._preferences_service:
            try:
                adv = self._preferences_service.get_advanced_settings()
                return getattr(adv, "genre_section_ttl", GENRE_SECTION_TTL_DEFAULT)
            except Exception:  # noqa: BLE001
                pass
        return GENRE_SECTION_TTL_DEFAULT

    async def get_cached_genre_section(
        self, source_key: str
    ) -> tuple[dict[str, str | None], dict[str, str | None]] | None:
        cache_key = f"{GENRE_SECTION_PREFIX}{source_key}"
        ttl = self._get_genre_section_ttl()

        if self._memory_cache:
            cached = await self._memory_cache.get(cache_key)
            if cached is not None:
                return cached

        if self._genre_section_dir:
            file_path = self._genre_section_dir / f"{source_key}.json"
            try:
                if file_path.exists():
                    data = json.loads(file_path.read_text())
                    built_at = data.get("built_at", 0)
                    if time.time() - built_at < ttl:
                        result = (data["genre_artists"], data["genre_artist_images"])
                        if self._memory_cache:
                            remaining = max(1, int(ttl - (time.time() - built_at)))
                            await self._memory_cache.set(cache_key, result, remaining)
                        return result
            except Exception:  # noqa: BLE001
                pass

        return None

    async def save_genre_section(
        self,
        source_key: str,
        genre_artists: dict[str, str | None],
        genre_artist_images: dict[str, str | None],
    ) -> None:
        cache_key = f"{GENRE_SECTION_PREFIX}{source_key}"
        ttl = self._get_genre_section_ttl()
        result = (genre_artists, genre_artist_images)

        if self._memory_cache:
            await self._memory_cache.set(cache_key, result, ttl)

        if self._genre_section_dir:
            file_path = self._genre_section_dir / f"{source_key}.json"
            try:
                payload = json.dumps({
                    "genre_artists": genre_artists,
                    "genre_artist_images": genre_artist_images,
                    "built_at": time.time(),
                })
                file_path.write_text(payload)
            except Exception:  # noqa: BLE001
                logger.warning("Failed to write genre section to disk for %s", source_key)

    async def build_and_cache_genre_section(
        self, source_key: str, genre_names: list[str]
    ) -> None:
        if source_key not in self._genre_build_locks:
            self._genre_build_locks[source_key] = asyncio.Lock()
        lock = self._genre_build_locks[source_key]
        if lock.locked():
            return
        async with lock:
            try:
                genre_artists = await self.get_genre_artists_batch(genre_names)
                genre_artist_images = await self.resolve_genre_artist_images(genre_artists)
                await self.save_genre_section(source_key, genre_artists, genre_artist_images)
            except Exception as exc:  # noqa: BLE001
                logger.error("Genre section build failed for source=%s: %s", source_key, exc)

    async def get_genre_artist(
        self, genre_name: str, exclude_mbids: set[str] | None = None
    ) -> str | None:
        cache_key = f"{GENRE_ARTIST_PREFIX}{genre_name.lower()}"

        if self._memory_cache and not exclude_mbids:
            cached = await self._memory_cache.get(cache_key)
            if cached is not None:
                return cached if cached != "" else None

        chosen: str | None = None
        try:
            artists = await self._mb_repo.search_artists_by_tag(genre_name, limit=10)
            first_valid: str | None = None
            for artist in artists:
                mbid = artist.musicbrainz_id
                if not mbid or mbid == VARIOUS_ARTISTS_MBID:
                    continue
                if exclude_mbids and mbid in exclude_mbids:
                    continue
                if first_valid is None:
                    first_valid = mbid
                # Prefer an artist AudioDB has a picture for so the tile shows art, not the gradient.
                if await self._artist_image_url(mbid):
                    chosen = mbid
                    break
            chosen = chosen or first_valid
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to fetch artist for genre '{genre_name}': {e}")

        if self._memory_cache and not exclude_mbids:
            await self._memory_cache.set(cache_key, chosen or "", GENRE_CACHE_TTL)

        return chosen

    async def get_genre_artists_batch(self, genres: list[str]) -> dict[str, str | None]:
        if not genres:
            return {}
        capped = genres[:20]

        raw_results = await asyncio.gather(
            *(self.get_genre_artist(genre) for genre in capped)
        )

        used_mbids: set[str] = set()
        results: dict[str, str | None] = {}
        for genre, mbid in zip(capped, raw_results):
            if mbid and mbid not in used_mbids:
                results[genre] = mbid
                used_mbids.add(mbid)
            elif mbid and mbid in used_mbids:
                alt = await self.get_genre_artist(genre, exclude_mbids=used_mbids)
                results[genre] = alt
                if alt:
                    used_mbids.add(alt)
            else:
                results[genre] = None
        return results

    def clear_disk_cache(self) -> int:
        """Delete all genre section JSON files from disk."""
        if not self._genre_section_dir or not self._genre_section_dir.exists():
            return 0
        count = 0
        for f in self._genre_section_dir.glob("*.json"):
            f.unlink(missing_ok=True)
            count += 1
        return count

    async def _artist_image_url(self, mbid: str) -> str | None:
        """Best AudioDB image URL for an artist, or None. Cached per-MBID on disk."""
        if not self._audiodb_image_service:
            return None
        try:
            images = await self._audiodb_image_service.fetch_and_cache_artist_images(mbid)
            if images and not images.is_negative:
                return images.wide_thumb_url or images.banner_url or images.fanart_url
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to fetch artist image for %s: %s", mbid, exc)
        return None

    async def resolve_genre_artist_images(
        self, genre_artists: dict[str, str | None]
    ) -> dict[str, str | None]:
        if not self._audiodb_image_service or not genre_artists:
            return {}

        sem = asyncio.Semaphore(5)

        async def _resolve_one(genre: str, mbid: str) -> tuple[str, str | None]:
            async with sem:
                return (genre, await self._artist_image_url(mbid))

        tasks = [
            _resolve_one(genre, mbid)
            for genre, mbid in genre_artists.items()
            if mbid
        ]
        if not tasks:
            return {}
        results = await asyncio.gather(*tasks)
        return {genre: url for genre, url in results if url}
