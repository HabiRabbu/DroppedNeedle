"""Bounded OpenSubsonic playback timeline sessions."""

from __future__ import annotations

import time
from collections import OrderedDict

import msgspec

from core.exceptions import ResourceNotFoundError
from services.compat.compat_scrobble_adapter import CompatScrobbleAdapter
from services.compat.library_view_service import LibraryViewService

_SESSION_TTL_SECONDS = 2 * 60 * 60


class _PlaybackSession(msgspec.Struct):
    position_ms: int
    stopped: bool
    submitted: bool
    updated_at: float


class PlaybackReportService:
    def __init__(
        self,
        scrobble: CompatScrobbleAdapter,
        view: LibraryViewService,
        *,
        max_sessions: int = 1_000,
    ) -> None:
        self._scrobble = scrobble
        self._view = view
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[tuple[str, str, str], _PlaybackSession] = (
            OrderedDict()
        )

    @property
    def session_count(self) -> int:
        self._evict()
        return len(self._sessions)

    async def report(
        self,
        file_id: str,
        *,
        user_id: str,
        user_name: str,
        client: str,
        position_ms: int,
        state: str,
        ignore_scrobble: bool,
    ) -> None:
        track = await self._view.get_track(file_id)
        if track is None:
            raise ResourceNotFoundError("Playback report song not found")
        self._evict()
        key = (user_id, client.casefold(), file_id)
        previous = self._sessions.pop(key, None)
        if state == "starting" or (
            previous is not None
            and previous.stopped
            and position_ms < previous.position_ms
        ):
            previous = None
        session = previous or _PlaybackSession(0, False, False, time.time())
        session.position_ms = position_ms
        session.updated_at = time.time()
        self._sessions[key] = session
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)

        if state == "starting":
            await self._scrobble.now_playing(
                file_id,
                user_id=user_id,
                user_name=user_name,
                client=client,
            )
            return
        if state in {"playing", "paused"}:
            await self._scrobble.progress(
                file_id,
                user_id=user_id,
                user_name=user_name,
                client=client,
                position_ms=position_ms,
                is_paused=state == "paused",
            )
            return

        session.stopped = True
        await self._scrobble.clear_presence(user_id, client)
        duration_ms = round(track.duration_seconds * 1000)
        threshold = min(duration_ms / 2, 240_000) if duration_ms > 0 else 240_000
        if not ignore_scrobble and not session.submitted and position_ms >= threshold:
            await self._scrobble.scrobble(
                file_id,
                user_id=user_id,
                user_name=user_name,
                client=client,
            )
            session.submitted = True

    def _evict(self) -> None:
        cutoff = time.time() - _SESSION_TTL_SECONDS
        while self._sessions:
            _key, session = next(iter(self._sessions.items()))
            if session.updated_at >= cutoff:
                break
            self._sessions.popitem(last=False)
