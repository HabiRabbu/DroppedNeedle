"""Shared integration checks and helpers used by HomeService and HomeChartsService."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from services.preferences_service import PreferencesService

logger = logging.getLogger(__name__)


def resolve_source_value(
    source: str | None, primary_source: str, lb_enabled: bool, lfm_enabled: bool
) -> str:
    """Per-user source resolution with no global preferences reads (Phase 5 / D1):
    honour an explicit source, else the user's primary, else whatever is linked."""
    if source in ("listenbrainz", "lastfm"):
        resolved = source
    else:
        resolved = primary_source
    if resolved == "listenbrainz" and not lb_enabled and lfm_enabled:
        return "lastfm"
    if resolved == "lastfm" and not lfm_enabled and lb_enabled:
        return "listenbrainz"
    return resolved


class HomeIntegrationHelpers:
    def __init__(self, preferences_service: PreferencesService):
        self._preferences = preferences_service

    def is_listenbrainz_enabled(self) -> bool:
        lb_settings = self._preferences.get_listenbrainz_connection()
        return lb_settings.enabled and bool(lb_settings.username)

    def is_jellyfin_enabled(self) -> bool:
        jf_settings = self._preferences.get_jellyfin_connection()
        return jf_settings.enabled and bool(jf_settings.jellyfin_url) and bool(jf_settings.api_key)

    def is_download_client_configured(self) -> bool:
        dc = self._preferences.get_download_client_settings()
        return dc.enabled and bool(dc.url)

    def is_library_configured(self) -> bool:
        # The native library scanner is always present.
        return True

    def is_youtube_enabled(self) -> bool:
        yt_settings = self._preferences.get_youtube_connection()
        return yt_settings.enabled

    def is_youtube_api_enabled(self) -> bool:
        yt_settings = self._preferences.get_youtube_connection()
        return yt_settings.enabled and yt_settings.api_enabled and yt_settings.has_valid_api_key()

    def is_local_files_enabled(self) -> bool:
        # Native engine always present; actual file presence is checked per-request via has_any_files().
        return True

    def is_navidrome_enabled(self) -> bool:
        nd_settings = self._preferences.get_navidrome_connection()
        return (
            nd_settings.enabled
            and bool(nd_settings.navidrome_url)
            and bool(nd_settings.username)
            and bool(nd_settings.password)
        )

    def is_plex_enabled(self) -> bool:
        plex_settings = self._preferences.get_plex_connection()
        return (
            plex_settings.enabled
            and bool(plex_settings.plex_url)
            and bool(plex_settings.plex_token)
            and bool(plex_settings.music_library_ids)
        )

    def is_lastfm_enabled(self) -> bool:
        return self._preferences.is_lastfm_enabled()

    def get_listenbrainz_username(self) -> str | None:
        lb_settings = self._preferences.get_listenbrainz_connection()
        return lb_settings.username if lb_settings.enabled else None

    def get_lastfm_username(self) -> str | None:
        lf_settings = self._preferences.get_lastfm_connection()
        return lf_settings.username if lf_settings.enabled else None

    def get_lb_username(self) -> str | None:
        lb_settings = self._preferences.get_listenbrainz_connection()
        if lb_settings.enabled and lb_settings.username:
            return lb_settings.username
        return None

    def resolve_source(self, source: str | None) -> str:
        if source in ("listenbrainz", "lastfm"):
            resolved = source
        else:
            resolved = self._preferences.get_primary_music_source().source
        lb_enabled = self.is_listenbrainz_enabled()
        lfm_enabled = self.is_lastfm_enabled()
        if resolved == "listenbrainz" and not lb_enabled and lfm_enabled:
            return "lastfm"
        if resolved == "lastfm" and not lfm_enabled and lb_enabled:
            return "listenbrainz"
        return resolved

    async def execute_tasks(self, tasks: dict[str, Any]) -> dict[str, Any]:
        if not tasks:
            return {}
        keys = list(tasks.keys())
        coros = list(tasks.values())
        raw_results = await asyncio.gather(*coros, return_exceptions=True)
        results = {}
        for key, result in zip(keys, raw_results):
            if isinstance(result, Exception):
                logger.warning(f"Task {key} failed: {result}")
                results[key] = None
            else:
                results[key] = result
        return results
