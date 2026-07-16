"""Collection-grounded artwork selection for every genre surface."""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from pathlib import Path

from api.v1.schemas.home import GenreArtwork, GenreArtworkAlbum
from infrastructure.cache.cache_keys import GENRE_ARTWORK_PREFIX
from infrastructure.cache.memory_cache import CacheInterface
from infrastructure.persistence.native_library_store import NativeLibraryStore
from services.home.cached_local_artwork_service import CachedLocalArtworkService

ALGORITHM_VERSION = "v2"
GENRE_ARTWORK_TTL_SECONDS = 86_400


class GenreArtworkService:
    def __init__(
        self,
        store: NativeLibraryStore,
        cache: CacheInterface,
        local_artwork: CachedLocalArtworkService,
        legacy_cache_dir: Path | None = None,
    ) -> None:
        self._store = store
        self._cache = cache
        self._local_artwork = local_artwork
        self._legacy_cache_dir = legacy_cache_dir
        self._legacy_cache_cleaned = False

    def _cleanup_legacy_cache(self) -> None:
        if self._legacy_cache_dir is None or not self._legacy_cache_dir.exists():
            return
        for path in list(self._legacy_cache_dir.glob("*.json"))[:100]:
            path.unlink(missing_ok=True)

    @staticmethod
    def _stable_key(genre_folded: str, album_id: str) -> str:
        return hashlib.sha256(f"{genre_folded}:{album_id}".encode()).hexdigest()

    @staticmethod
    def _cache_key(genre_folded: str, revision: int) -> str:
        return f"{GENRE_ARTWORK_PREFIX}{genre_folded}:{ALGORITHM_VERSION}:{revision}"

    async def _cached_is_current(
        self, cached: GenreArtwork, candidates: list[dict[str, object]]
    ) -> bool:
        if not cached.albums:
            return True
        by_id = {str(row["album_id"]): row for row in candidates}
        for album in cached.albums:
            candidate = by_id.get(album.album_id)
            if (
                candidate is None
                or int(candidate["cover_version"]) != album.cover_version
            ):
                return False
            if await self._local_artwork.read(candidate) is None:
                return False
        return True

    async def _select(
        self,
        genre_folded: str,
        revision: int,
        candidates: list[dict[str, object]],
    ) -> GenreArtwork:
        by_count: dict[int, list[dict[str, object]]] = defaultdict(list)
        for candidate in candidates:
            by_count[int(candidate["match_count"])].append(candidate)

        selected: list[GenreArtworkAlbum] = []
        selected_artists: set[str] = set()
        selected_covers: set[str] = set()
        for match_count in sorted(by_count, reverse=True):
            remaining = sorted(
                by_count[match_count],
                key=lambda row: self._stable_key(genre_folded, str(row["album_id"])),
            )
            while remaining and len(selected) < 4:
                unseen = [
                    row
                    for row in remaining
                    if str(
                        row.get("album_artist_id") or row.get("album_artist_name") or ""
                    )
                    not in selected_artists
                ]
                candidate = (unseen or remaining)[0]
                remaining.remove(candidate)
                resolved = await self._local_artwork.read(candidate)
                if resolved is None or resolved[3] in selected_covers:
                    continue
                artist_key = str(
                    candidate.get("album_artist_id")
                    or candidate.get("album_artist_name")
                    or ""
                )
                selected_artists.add(artist_key)
                selected_covers.add(resolved[3])
                selected.append(
                    GenreArtworkAlbum(
                        album_id=str(candidate["album_id"]),
                        album_title=str(candidate["album_title"]),
                        album_artist_name=(
                            str(candidate["album_artist_name"])
                            if candidate.get("album_artist_name") is not None
                            else None
                        ),
                        cover_version=int(candidate["cover_version"]),
                    )
                )
            if len(selected) == 4:
                break

        digest = hashlib.sha256(
            "|".join(
                f"{album.album_id}:{album.cover_version}" for album in selected
            ).encode()
        ).hexdigest()[:12]
        return GenreArtwork(
            kind="collage" if selected else "gradient",
            albums=selected,
            version=f"{ALGORITHM_VERSION}:{revision}:{digest}",
        )

    async def get_artwork_batch(self, genres: list[str]) -> dict[str, GenreArtwork]:
        if not self._legacy_cache_cleaned:
            await asyncio.to_thread(self._cleanup_legacy_cache)
            self._legacy_cache_cleaned = True
        rows_by_genre = await self._store.list_genre_artwork_candidates(genres)
        result: dict[str, GenreArtwork] = {}
        for display_name, data in rows_by_genre.items():
            folded = str(data["genre_folded"])
            revision = int(data["revision"])
            candidates = list(data["candidates"])
            key = self._cache_key(folded, revision)
            cached = await self._cache.get(key)
            if isinstance(cached, GenreArtwork) and await self._cached_is_current(
                cached, candidates
            ):
                result[display_name] = cached
                continue
            artwork = await self._select(folded, revision, candidates)
            await self._cache.set(key, artwork, GENRE_ARTWORK_TTL_SECONDS)
            result[display_name] = artwork
        return result
