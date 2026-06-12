from datetime import datetime
from typing import Any, TYPE_CHECKING
from models.library import LibraryAlbum, LibraryGroupedAlbum, LibraryGroupedArtist
from infrastructure.cover_urls import prefer_release_group_cover_url
from infrastructure.cache.cache_keys import (
    lidarr_library_albums_key,
    lidarr_library_artists_key,
    lidarr_library_mbids_key,
    lidarr_artist_mbids_key,
    lidarr_library_grouped_key,
    lidarr_requested_mbids_key,
    lidarr_monitored_mbids_key,
)
from .base import LidarrBase, LIDARR_LIBRARY_SCAN_TTL_SECONDS

if TYPE_CHECKING:
    from infrastructure.persistence.request_history import RequestHistoryStore


class LidarrLibraryRepository(LidarrBase):
    _request_history_store: "RequestHistoryStore | None" = None

    async def get_library(self, include_unmonitored: bool = False) -> list[LibraryAlbum]:
        cache_key = lidarr_library_albums_key(include_unmonitored)
        cached_result = await self._cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        data = await self._get_all_albums_raw()
        out: list[LibraryAlbum] = []
        filtered_count = 0

        for item in data:
            is_monitored = item.get("monitored", False)
            statistics = item.get("statistics", {})
            has_files = statistics.get("trackFileCount", 0) > 0

            if not is_monitored and not include_unmonitored:
                filtered_count += 1
                continue

            if not has_files:
                filtered_count += 1
                continue

            artist_data = item.get("artist", {})
            artist = artist_data.get("artistName", "Unknown")
            artist_mbid = artist_data.get("foreignArtistId")

            year = None
            if date := item.get("releaseDate"):
                try:
                    year = int(date.split("-")[0])
                except ValueError:
                    pass

            album_id = item.get("id")
            album_mbid = item.get("foreignAlbumId")
            cover = prefer_release_group_cover_url(
                album_mbid,
                self._get_album_cover_url(item.get("images", []), album_id),
                size=500,
            )

            date_added = None
            if added_str := item.get("added"):
                try:
                    dt = datetime.fromisoformat(added_str.replace('Z', '+00:00'))
                    date_added = int(dt.timestamp())
                except Exception:  # noqa: BLE001
                    pass

            out.append(
                LibraryAlbum(
                    artist=artist,
                    album=item.get("title"),
                    year=year,
                    monitored=item.get("monitored", False),
                    quality=None,
                    cover_url=cover,
                    musicbrainz_id=album_mbid,
                    artist_mbid=artist_mbid,
                    date_added=date_added,
                )
            )

        await self._cache.set(cache_key, out, ttl_seconds=LIDARR_LIBRARY_SCAN_TTL_SECONDS)
        return out

    async def get_artists_from_library(self, include_unmonitored: bool = False) -> list[dict]:
        cache_key = lidarr_library_artists_key(include_unmonitored)
        cached_result = await self._cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        albums_data = await self._get_all_albums_raw()
        artists_dict: dict[str, dict] = {}
        filtered_count = 0

        for item in albums_data:
            is_monitored = item.get("monitored", False)
            statistics = item.get("statistics", {})
            has_files = statistics.get("trackFileCount", 0) > 0

            if not is_monitored and not include_unmonitored:
                filtered_count += 1
                continue

            if not has_files:
                filtered_count += 1
                continue

            artist_data = item.get("artist", {})
            artist_mbid = artist_data.get("foreignArtistId")
            artist_name = artist_data.get("artistName", "Unknown")

            if not artist_mbid:
                continue

            date_added = None
            if added_str := item.get("added"):
                try:
                    dt = datetime.fromisoformat(added_str.replace('Z', '+00:00'))
                    date_added = int(dt.timestamp())
                except Exception:  # noqa: BLE001
                    pass

            if artist_mbid not in artists_dict:
                artists_dict[artist_mbid] = {
                    'mbid': artist_mbid,
                    'name': artist_name,
                    'album_count': 0,
                    'date_added': date_added
                }

            artists_dict[artist_mbid]['album_count'] += 1
            if date_added and (not artists_dict[artist_mbid]['date_added'] or
                              date_added < artists_dict[artist_mbid]['date_added']):
                artists_dict[artist_mbid]['date_added'] = date_added

        result = list(artists_dict.values())
        await self._cache.set(cache_key, result, ttl_seconds=LIDARR_LIBRARY_SCAN_TTL_SECONDS)
        return result

    async def get_library_grouped(self) -> list[LibraryGroupedArtist]:
        cache_key = lidarr_library_grouped_key()
        cached_result = await self._cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        data = await self._get_all_albums_raw()
        grouped: dict[str, list[LibraryGroupedAlbum]] = {}

        for item in data:
            statistics = item.get("statistics", {})
            if statistics.get("trackFileCount", 0) == 0:
                continue

            artist = item.get("artist", {}).get("artistName", "Unknown")
            title = item.get("title")
            year = None
            if date := item.get("releaseDate"):
                try:
                    year = int(date.split("-")[0])
                except ValueError:
                    pass

            album_id = item.get("id")
            album_mbid = item.get("foreignAlbumId")
            cover = prefer_release_group_cover_url(
                album_mbid,
                self._get_album_cover_url(item.get("images", []), album_id),
                size=500,
            )

            grouped.setdefault(artist, []).append(
                LibraryGroupedAlbum(
                    title=title,
                    year=year,
                    monitored=item.get("monitored", False),
                    cover_url=cover,
                )
            )

        result = [
            LibraryGroupedArtist(artist=artist, albums=albums)
            for artist, albums in grouped.items()
        ]
        await self._cache.set(cache_key, result, ttl_seconds=LIDARR_LIBRARY_SCAN_TTL_SECONDS)
        return result

    async def get_library_mbids(self, include_release_ids: bool = True) -> set[str]:
        cache_key = lidarr_library_mbids_key(include_release_ids)

        cached_result = await self._cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        data = await self._get_all_albums_raw()
        ids: set[str] = set()
        for item in data:
            statistics = item.get("statistics", {})
            track_file_count = statistics.get("trackFileCount", 0)
            if track_file_count == 0:
                continue

            rg = item.get("foreignAlbumId")
            if isinstance(rg, str):
                ids.add(rg.lower())
            if include_release_ids:
                for rel in item.get("releases", []) or []:
                    rid = rel.get("foreignId")
                    if isinstance(rid, str):
                        ids.add(rid.lower())

        await self._cache.set(cache_key, ids, ttl_seconds=LIDARR_LIBRARY_SCAN_TTL_SECONDS)
        return ids

    async def get_artist_mbids(self) -> set[str]:
        cache_key = lidarr_artist_mbids_key()

        cached_result = await self._cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        data = await self._get("/api/v1/artist")
        ids: set[str] = set()
        for item in data:
            is_monitored = item.get("monitored", False)
            has_files = item.get("statistics", {}).get("trackFileCount", 0) > 0
            if not is_monitored and not has_files:
                continue
            mbid = item.get("foreignArtistId") or item.get("mbId")
            if isinstance(mbid, str):
                ids.add(mbid.lower())

        await self._cache.set(cache_key, ids, ttl_seconds=LIDARR_LIBRARY_SCAN_TTL_SECONDS)
        return ids

    async def get_requested_mbids(self) -> set[str]:
        """Return MBIDs of albums with active requests in MusicSeerr."""
        if self._request_history_store is not None:
            try:
                return await self._request_history_store.async_get_active_mbids()
            except Exception:  # noqa: BLE001
                return set()
        return set()

    async def get_monitored_no_files_mbids(self) -> set[str]:
        """Return monitored Lidarr albums that have no downloaded track files."""
        cache_key = lidarr_monitored_mbids_key()

        cached_result = await self._cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        data = await self._get_all_albums_raw()
        ids: set[str] = set()
        for item in data:
            if not item.get("monitored", False):
                continue

            statistics = item.get("statistics", {})
            track_file_count = statistics.get("trackFileCount", 0)
            if track_file_count > 0:
                continue

            rg = item.get("foreignAlbumId")
            if isinstance(rg, str):
                ids.add(rg.lower())

        await self._cache.set(cache_key, ids, ttl_seconds=LIDARR_LIBRARY_SCAN_TTL_SECONDS)
        return ids
