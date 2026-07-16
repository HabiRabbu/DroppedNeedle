"""Local-ID cover adapter for the isolated target compatibility composition."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infrastructure.persistence.native_library_store import NativeLibraryStore
    from repositories.coverart_repository import CoverArtRepository
    from repositories.coverart_disk_cache import CoverDiskCache
    from services.home.cached_local_artwork_service import CachedLocalArtworkService


class TargetCoverArtService:
    def __init__(
        self,
        store: "NativeLibraryStore",
        provider_covers: "CoverArtRepository",
        local_artwork: "CachedLocalArtworkService",
    ) -> None:
        self._store = store
        self._provider = provider_covers
        self._local = local_artwork
        self._album_provider_ids: dict[str, str] = {}
        self._artist_provider_ids: dict[str, str] = {}

    @property
    def disk_cache(self) -> "CoverDiskCache":
        return self._provider.disk_cache

    def is_rg_cover_warming(self, album_id: str, size: str | None = "500") -> bool:
        checker = getattr(self._provider, "is_rg_cover_warming", None)
        if not callable(checker):
            return False
        return bool(checker(self._album_provider_ids.get(album_id, album_id), size))

    def is_artist_cover_warming(self, artist_id: str, size: int | None = None) -> bool:
        checker = getattr(self._provider, "is_artist_cover_warming", None)
        if not callable(checker):
            return False
        return bool(checker(self._artist_provider_ids.get(artist_id, artist_id), size))

    @staticmethod
    def _remember_provider_id(
        mappings: dict[str, str], identifier: str, context: dict
    ) -> str | None:
        provider_id = context.get("provider_id")
        if provider_id:
            value = str(provider_id)
            mappings[identifier] = value
            mappings[value] = value
            return value
        return None

    async def get_release_group_cover(
        self,
        album_id: str,
        size: str | None = "500",
        **kwargs,
    ) -> tuple[bytes, str, str] | None:
        context = await self._store.get_target_artwork_context("album", album_id)
        if context is None:
            return await self._provider.get_release_group_cover(
                album_id, size, **kwargs
            )
        provider_id = self._remember_provider_id(
            self._album_provider_ids, album_id, context
        )
        local = await self._local.read(context)
        if local is not None:
            return local[:3]
        if provider_id:
            return await self._provider.get_release_group_cover(
                provider_id, size, **kwargs
            )
        return None

    async def get_release_group_cover_etag(
        self, album_id: str, size: str | None = "500"
    ) -> str | None:
        context = await self._store.get_target_artwork_context("album", album_id)
        if context is None:
            return await self._provider.get_release_group_cover_etag(album_id, size)
        provider_id = self._remember_provider_id(
            self._album_provider_ids, album_id, context
        )
        local = await self._local.read(context)
        if local is not None:
            return local[3]
        if provider_id:
            return await self._provider.get_release_group_cover_etag(provider_id, size)
        return None

    async def get_release_cover(
        self,
        release_id: str,
        size: str | None = "500",
        **kwargs,
    ) -> tuple[bytes, str, str] | None:
        return await self._provider.get_release_cover(release_id, size, **kwargs)

    async def get_release_cover_etag(
        self, release_id: str, size: str | None = "500"
    ) -> str | None:
        return await self._provider.get_release_cover_etag(release_id, size)

    async def batch_prefetch_covers(
        self,
        album_ids: list[str],
        size: str = "250",
        max_concurrent: int = 5,
    ) -> None:
        provider_ids: list[str] = []
        seen: set[str] = set()
        for album_id in album_ids:
            context = await self._store.get_target_artwork_context("album", album_id)
            provider_id = (
                album_id
                if context is None
                else self._remember_provider_id(
                    self._album_provider_ids, album_id, context
                )
            )
            if provider_id and provider_id not in seen:
                seen.add(provider_id)
                provider_ids.append(provider_id)
        await self._provider.batch_prefetch_covers(provider_ids, size, max_concurrent)

    async def get_artist_image(
        self, artist_id: str, size: int | None = None, **kwargs
    ) -> tuple[bytes, str, str] | None:
        context = await self._store.get_target_artwork_context("artist", artist_id)
        if context is None:
            return await self._provider.get_artist_image(artist_id, size, **kwargs)
        provider_id = self._remember_provider_id(
            self._artist_provider_ids, artist_id, context
        )
        if not provider_id:
            return None
        return await self._provider.get_artist_image(provider_id, size, **kwargs)

    async def get_artist_image_etag(
        self, artist_id: str, size: int | None = None
    ) -> str | None:
        context = await self._store.get_target_artwork_context("artist", artist_id)
        if context is None:
            return await self._provider.get_artist_image_etag(artist_id, size)
        provider_id = self._remember_provider_id(
            self._artist_provider_ids, artist_id, context
        )
        if not provider_id:
            return None
        return await self._provider.get_artist_image_etag(provider_id, size)

    async def debug_artist_image(self, artist_id: str, debug_info: dict) -> dict:
        context = await self._store.get_target_artwork_context("artist", artist_id)
        if context is not None:
            provider_id = self._remember_provider_id(
                self._artist_provider_ids, artist_id, context
            )
            if provider_id:
                artist_id = provider_id
        return await self._provider.debug_artist_image(artist_id, debug_info)
