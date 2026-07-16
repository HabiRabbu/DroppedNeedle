"""Chooses the acquisition backend for a request.

A user-configured download client (slskd or Usenet) wins when one is set up;
otherwise the request goes to Free Music (D24), the native lawful client. This is
the single place that choice is made, so every acquisition path - interactive
album and track requests, batch requests, Weekly Mix, new-release auto-download,
and request approvals routes the same way. The wanted watcher remains on the
built-in client because it needs source scouting and partial-track acquisition.
After 2.0 deletes slskd and Usenet, that watcher will be reworked separately and
this dispatcher will always route to Free Music.

The method signatures mirror ``DownloadService`` exactly, so a call site swaps the
receiver and nothing else. Free Music ignores the args it has no use for (year,
origin, dedup, duration) and never returns the ``ALREADY_IN_LIBRARY`` sentinel -
its own drop-import handoff skips or upgrades an owned album after the fact.
"""

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from services.native.download_service import DownloadService
    from services.native.free_music_service import FreeMusicService
    from services.preferences_service import PreferencesService
    from services.native.library_ownership_service import LibraryOwnershipService

logger = logging.getLogger(__name__)


class AcquisitionDispatcher:
    def __init__(
        self,
        *,
        get_download_service: "Callable[[], DownloadService]",
        get_free_music_service: "Callable[[], FreeMusicService]",
        preferences_service: "PreferencesService",
        ownership_service: "LibraryOwnershipService | None" = None,
    ) -> None:
        # both resolved fresh per call: a settings save rebuilds the DownloadService
        # singleton, and Free Music reads its own settings per request
        self._get_download_service = get_download_service
        self._get_free_music_service = get_free_music_service
        self._prefs = preferences_service
        self._ownership = ownership_service

    def _use_free_music(self) -> bool:
        if self._prefs.is_builtin_download_ready():
            return False
        return self._get_free_music_service().is_ready()

    async def request_album(
        self,
        user_id: str,
        release_group_mbid: str,
        artist_name: str,
        album_title: str,
        year: int | None = None,
        track_count: int | None = None,
        recording_mbid: str | None = None,
        track_title: str | None = None,
        track_duration_seconds: float | None = None,
        download_type: str = "album",
        artist_mbid: str | None = None,
        origin: str = "user",
        release_mbid: str | None = None,
    ) -> str:
        if self._ownership is not None:
            release_group_mbid = await self._ownership.provider_album_id(
                release_group_mbid
            )
            if recording_mbid is not None:
                recording_mbid = await self._ownership.provider_track_id(recording_mbid)
            if artist_mbid is not None:
                artist_mbid = await self._ownership.provider_artist_id(artist_mbid)
        if self._use_free_music():
            return await self._get_free_music_service().request_album(
                user_id=user_id,
                release_group_mbid=release_group_mbid,
                artist_name=artist_name,
                album_title=album_title,
                track_count=track_count or 0,
            )
        return await self._get_download_service().request_album(
            user_id=user_id,
            release_group_mbid=release_group_mbid,
            artist_name=artist_name,
            album_title=album_title,
            year=year,
            track_count=track_count,
            recording_mbid=recording_mbid,
            track_title=track_title,
            track_duration_seconds=track_duration_seconds,
            download_type=download_type,
            artist_mbid=artist_mbid,
            origin=origin,
            release_mbid=release_mbid,
        )

    async def request_track(
        self,
        user_id: str,
        recording_mbid: str,
        artist_name: str,
        track_title: str,
        album_title: str | None = None,
        duration_seconds: int | None = None,
        release_group_mbid: str | None = None,
        artist_mbid: str | None = None,
        origin: str = "user",
        release_mbid: str | None = None,
    ) -> str:
        if self._ownership is not None:
            recording_mbid = await self._ownership.provider_track_id(recording_mbid)
            if release_group_mbid is not None:
                release_group_mbid = await self._ownership.provider_album_id(
                    release_group_mbid
                )
            if artist_mbid is not None:
                artist_mbid = await self._ownership.provider_artist_id(artist_mbid)
        if self._use_free_music():
            return await self._get_free_music_service().request_track(
                user_id=user_id,
                recording_mbid=recording_mbid,
                artist_name=artist_name,
                track_title=track_title,
            )
        return await self._get_download_service().request_track(
            user_id=user_id,
            recording_mbid=recording_mbid,
            artist_name=artist_name,
            track_title=track_title,
            album_title=album_title,
            duration_seconds=duration_seconds,
            release_group_mbid=release_group_mbid,
            artist_mbid=artist_mbid,
            origin=origin,
            release_mbid=release_mbid,
        )
