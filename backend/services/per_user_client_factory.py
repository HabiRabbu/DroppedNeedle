"""Resolve request-scoped ListenBrainz / Last.fm clients for a user from their
encrypted ``user_connections``.

Factory is a singleton; the clients it returns are per-request. Last.fm builds from
the global app api_key/shared_secret (one registered app) plus the user's per-user
session_key. Username is exposed separately via ``resolve_lastfm_username`` because
the Last.fm repo holds no username field (reads take it per-method-call).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.config import Settings
from infrastructure.cache.memory_cache import CacheInterface
from infrastructure.http.client import get_http_client, get_listenbrainz_http_client
from infrastructure.persistence.user_connections_store import UserConnectionsStore
from services.preferences_service import PreferencesService

if TYPE_CHECKING:
    from repositories.lastfm_repository import LastFmRepository
    from repositories.listenbrainz_repository import ListenBrainzRepository

_LISTENBRAINZ = "listenbrainz"
_LASTFM = "lastfm"


class PerUserClientFactory:
    def __init__(
        self,
        connections_store: UserConnectionsStore,
        preferences_service: PreferencesService,
        cache: CacheInterface,
        settings: Settings,
    ):
        self._connections_store = connections_store
        self._preferences_service = preferences_service
        self._cache = cache
        self._settings = settings

    def _http_timeouts(self) -> tuple[float, float, int]:
        advanced = self._preferences_service.get_advanced_settings()
        return (
            float(advanced.http_timeout),
            float(advanced.http_connect_timeout),
            advanced.http_max_connections,
        )

    async def resolve_listenbrainz(self, user_id: str) -> "ListenBrainzRepository | None":
        data = await self._connections_store.get(user_id, _LISTENBRAINZ)
        if not data:
            return None
        user_token = data.get("user_token", "")
        if not user_token:
            return None

        from repositories.listenbrainz_repository import ListenBrainzRepository

        timeout, connect_timeout, _ = self._http_timeouts()
        http_client = get_listenbrainz_http_client(
            settings=self._settings, timeout=timeout, connect_timeout=connect_timeout
        )
        return ListenBrainzRepository(
            http_client=http_client,
            cache=self._cache,
            username=data.get("username", ""),
            user_token=user_token,
        )

    async def resolve_lastfm(self, user_id: str) -> "LastFmRepository | None":
        data = await self._connections_store.get(user_id, _LASTFM)
        if not data:
            return None
        session_key = data.get("session_key", "")
        if not session_key:
            return None
        lf = self._preferences_service.get_lastfm_connection()
        if not (lf.api_key and lf.shared_secret):
            return None

        from repositories.lastfm_repository import LastFmRepository

        timeout, connect_timeout, max_connections = self._http_timeouts()
        http_client = get_http_client(
            self._settings,
            timeout=timeout,
            connect_timeout=connect_timeout,
            max_connections=max_connections,
        )
        return LastFmRepository(
            http_client=http_client,
            cache=self._cache,
            api_key=lf.api_key,
            shared_secret=lf.shared_secret,
            session_key=session_key,
        )

    async def resolve_lastfm_username(self, user_id: str) -> str | None:
        data = await self._connections_store.get(user_id, _LASTFM)
        if not data:
            return None
        return data.get("username") or None

    async def resolve_listenbrainz_username(self, user_id: str) -> str | None:
        data = await self._connections_store.get(user_id, _LISTENBRAINZ)
        if not data:
            return None
        return data.get("username") or None

    async def is_listenbrainz_linked(self, user_id: str) -> bool:
        """Lightweight enable check (no client build) mirroring resolve_listenbrainz."""
        data = await self._connections_store.get(user_id, _LISTENBRAINZ)
        return bool(data and data.get("user_token"))

    async def is_lastfm_linked(self, user_id: str) -> bool:
        """Lightweight enable check (no client build) mirroring resolve_lastfm."""
        data = await self._connections_store.get(user_id, _LASTFM)
        if not (data and data.get("session_key")):
            return False
        lf = self._preferences_service.get_lastfm_connection()
        return bool(lf.api_key and lf.shared_secret)
