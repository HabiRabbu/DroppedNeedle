"""Compat scrobble adapter: protocol play event -> ScrobbleService.

Forwards to the existing ScrobbleService so compat plays land in ``play_history``
and forward to Last.fm/ListenBrainz like native plays. Stream/`/universal`
requests are never counted - only an explicit Subsonic ``scrobble`` or a Jellyfin
``Sessions/Playing/Stopped`` past threshold.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from api.v1.schemas.scrobble import NowPlayingRequest, ScrobbleRequest
from core.exceptions import ResourceNotFoundError

if TYPE_CHECKING:
    from api.v1.schemas.scrobble import ScrobbleResponse
    from services.compat.library_view_service import LibraryViewService
    from services.compat.view_models import ViewTrack
    from services.scrobble_service import ScrobbleService

_START_TTL_SECONDS = 2 * 60 * 60  # a stuck session can't leak its start time


def _norm_client(client: str | None) -> str | None:
    if not client:
        return None
    return client.strip().lower() or None


class CompatScrobbleAdapter:
    def __init__(
        self,
        scrobble_service: "ScrobbleService",
        library_view_service: "LibraryViewService",
    ) -> None:
        self._scrobble = scrobble_service
        self._view = library_view_service
        # (user_id, ItemId|PlaySessionId) -> started_at unix
        self._starts: dict[tuple[str, str], float] = {}

    async def now_playing(
        self, file_id: str, *, user_id: str, client: str | None
    ) -> "ScrobbleResponse":
        track = await self._resolve(file_id)
        req = NowPlayingRequest(
            track_name=track.title,
            artist_name=track.artist_name,
            album_name=track.album_title,
            duration_ms=round(track.duration_seconds * 1000),
            mbid=track.recording_mbid,
            source=_norm_client(client),
            release_group_mbid=track.rg_mbid,
        )
        return await self._scrobble.report_now_playing(req, user_id=user_id)

    async def scrobble(
        self,
        file_id: str,
        *,
        user_id: str,
        client: str | None,
        played_at: float | None = None,
    ) -> "ScrobbleResponse":
        track = await self._resolve(file_id)
        ts = int(played_at if played_at is not None else time.time())
        req = ScrobbleRequest(
            track_name=track.title,
            artist_name=track.artist_name,
            timestamp=ts,
            album_name=track.album_title,
            duration_ms=round(track.duration_seconds * 1000),
            mbid=track.recording_mbid,
            source=_norm_client(client),
            release_group_mbid=track.rg_mbid,
        )
        return await self._scrobble.submit_scrobble(req, user_id=user_id)

    async def _resolve(self, file_id: str) -> "ViewTrack":
        track = await self._view.get_track(file_id)
        if track is None:
            raise ResourceNotFoundError(f"Track {file_id} not found")
        return track

    def mark_started(self, user_id: str, key: str) -> None:
        self._evict_stale()
        self._starts[(user_id, key)] = time.time()

    def pop_started(self, user_id: str, key: str) -> float | None:
        self._evict_stale()
        return self._starts.pop((user_id, key), None)

    def _evict_stale(self) -> None:
        cutoff = time.time() - _START_TTL_SECONDS
        for k in [k for k, v in self._starts.items() if v < cutoff]:
            self._starts.pop(k, None)
