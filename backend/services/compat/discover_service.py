"""Compat discovery: owned-local hybrid, no outbound by default.

All results are intersected with the active owned library so everything returned
actually streams. The similar-songs related pool is gated by
``ConnectAppsSettings.discover_mode``:

    local-only            same-artist pool only (no outbound). DEFAULT.
    lazy-mb               + related artists fetched from MusicBrainz ONCE per
                          artist and cached in library_artists.related_artist_mbids.
    use-scrobble-targets  + ArtistDiscoveryService when the user has
                          Last.fm/ListenBrainz configured, else local.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from infrastructure.persistence.auth_store import UserRecord
    from infrastructure.persistence.library_db import LibraryDB
    from infrastructure.persistence.play_history_store import PlayHistoryStore
    from services.artist_discovery_service import ArtistDiscoveryService
    from services.compat.library_view_service import LibraryViewService
    from services.compat.view_models import ViewAlbum, ViewTrack
    from services.per_user_client_factory import PerUserClientFactory
    from services.preferences_service import PreferencesService

logger = logging.getLogger(__name__)

RelatedFetcher = Callable[[str], Awaitable[list[str]]]


def _looks_like_real_mbid(value: str) -> bool:
    # real MusicBrainz MBIDs are dashed UUIDs; synthetic ids are dashless
    return "-" in value


class CompatDiscoverService:
    def __init__(
        self,
        *,
        library_db: "LibraryDB",
        library_view_service: "LibraryViewService",
        preferences_service: "PreferencesService",
        play_history_store: "PlayHistoryStore",
        artist_discovery_service: "ArtistDiscoveryService | None" = None,
        client_factory: "PerUserClientFactory | None" = None,
        related_artists_fetcher: RelatedFetcher | None = None,
    ) -> None:
        self._db = library_db
        self._view = library_view_service
        self._preferences = preferences_service
        self._play_history = play_history_store
        self._artist_discovery = artist_discovery_service
        self._client_factory = client_factory
        self._related_fetcher = related_artists_fetcher

    async def get_top_songs(
        self, artist_name: str, *, user_id: str, count: int = 50,
        user: "UserRecord | None" = None,
    ) -> list["ViewTrack"]:
        counts = await self._play_history.play_counts_by_artist(user_id, artist_name)
        files = await self._db.get_files_by_artist_name(
            artist_name, limit=max(count * 4, count)
        )

        def plays(row: dict) -> int:
            rec = row.get("recording_mbid")
            if rec and f"rec:{rec}" in counts:
                return counts[f"rec:{rec}"]
            return counts.get(f"name:{(row.get('track_title') or '').lower()}", 0)

        # stable sort: most-played first, recency (query order) breaks ties
        files.sort(key=plays, reverse=True)
        return await self._view.tracks_from_rows(files[:count], user=user)

    async def get_history_albums(
        self,
        *,
        user_id: str,
        frequent: bool,
        limit: int,
        offset: int,
        user: "UserRecord | None" = None,
    ) -> list["ViewAlbum"]:
        ids = await self._play_history.album_ids(
            user_id, frequent=frequent, limit=limit, offset=offset
        )
        return await self._view.get_albums_by_ids(ids, user=user)

    async def get_random_songs(
        self, *, count: int = 50, genre: str | None = None,
        from_year: int | None = None, to_year: int | None = None,
        user: "UserRecord | None" = None,
    ) -> list["ViewTrack"]:
        rows = await self._db.get_random_files(
            limit=count, genre=genre, from_year=from_year, to_year=to_year
        )
        return await self._view.tracks_from_rows(rows, user=user)

    async def get_similar_songs(
        self, artist_mbid: str, *, user_id: str, count: int = 50,
        user: "UserRecord | None" = None,
    ) -> list["ViewTrack"]:
        mbids = [artist_mbid]  # same-artist pool always included
        for m in await self._related_mbids(artist_mbid, user_id):
            if m and m not in mbids:
                mbids.append(m)
        rows = await self._db.get_files_by_artist_mbids(mbids, limit=count)
        return await self._view.tracks_from_rows(rows, user=user)

    async def _related_mbids(self, artist_mbid: str, user_id: str) -> list[str]:
        mode = self._preferences.get_connect_apps_settings().discover_mode
        if mode == "lazy-mb":
            return await self._lazy_mb_related(artist_mbid)
        if mode == "use-scrobble-targets":
            return await self._scrobble_target_related(artist_mbid, user_id)
        return []  # local-only

    async def _lazy_mb_related(self, artist_mbid: str) -> list[str]:
        cached = await self._db.get_related_artist_mbids(artist_mbid)
        if cached is not None:
            return [m for m in cached.split(",") if m]
        # synthetic ids can't resolve in MusicBrainz; cache empty so we don't
        # retry every request.
        if self._related_fetcher is None or not _looks_like_real_mbid(artist_mbid):
            await self._db.set_related_artist_mbids(artist_mbid, "")
            return []
        try:
            related = await self._related_fetcher(artist_mbid) or []
        except Exception:  # noqa: BLE001 - discovery must never fail the request
            logger.warning("lazy-mb related fetch failed for %s", artist_mbid[:8], exc_info=True)
            related = []
        await self._db.set_related_artist_mbids(artist_mbid, ",".join(related))
        return related

    async def _scrobble_target_related(self, artist_mbid: str, user_id: str) -> list[str]:
        if self._artist_discovery is None or not await self._has_scrobble_targets(user_id):
            return []
        resp = await self._artist_discovery.get_similar_artists(
            artist_mbid, user_id=user_id
        )
        return [a.musicbrainz_id for a in resp.similar_artists if a.musicbrainz_id]

    async def _has_scrobble_targets(self, user_id: str) -> bool:
        if self._client_factory is None:
            return False
        if await self._client_factory.resolve_lastfm(user_id) is not None:
            return True
        return await self._client_factory.resolve_listenbrainz(user_id) is not None
