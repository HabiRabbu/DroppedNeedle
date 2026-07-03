import logging

from api.v1.schemas.discover import (
    DiscoverIntegrationStatus,
    QueueSettings,
)
from services.preferences_service import PreferencesService

logger = logging.getLogger(__name__)

DISCOVER_CACHE_KEY = "discover_response"


class IntegrationHelpers:
    def __init__(self, preferences_service: PreferencesService) -> None:
        self._preferences = preferences_service

    def is_listenbrainz_enabled(self) -> bool:
        lb_settings = self._preferences.get_listenbrainz_connection()
        return lb_settings.enabled and bool(lb_settings.username)

    def is_jellyfin_enabled(self) -> bool:
        jf_settings = self._preferences.get_jellyfin_connection()
        return jf_settings.enabled and bool(jf_settings.jellyfin_url) and bool(jf_settings.api_key)

    def is_download_client_configured(self) -> bool:
        # Any acquisition source counts - slskd (Soulseek) OR SABnzbd (Usenet).
        return self._preferences.is_download_source_ready()

    def is_library_configured(self) -> bool:
        # The native library scanner is always present.
        return True

    def is_youtube_api_enabled(self) -> bool:
        yt_settings = self._preferences.get_youtube_connection()
        return yt_settings.enabled and yt_settings.api_enabled and yt_settings.has_valid_api_key()

    def is_lastfm_enabled(self) -> bool:
        return self._preferences.is_lastfm_enabled()

    def get_listenbrainz_username(self) -> str | None:
        lb_settings = self._preferences.get_listenbrainz_connection()
        return lb_settings.username if lb_settings.enabled else None

    def get_lastfm_username(self) -> str | None:
        lf_settings = self._preferences.get_lastfm_connection()
        return lf_settings.username if lf_settings.enabled else None

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

    def get_queue_settings(self) -> QueueSettings:
        adv = self._preferences.get_advanced_settings()
        return QueueSettings(
            queue_size=adv.discover_queue_size,
            queue_ttl=adv.discover_queue_ttl,
            seed_artists=adv.discover_queue_seed_artists,
            wildcard_slots=adv.discover_queue_wildcard_slots,
            similar_artists_limit=adv.discover_queue_similar_artists_limit,
            albums_per_similar=adv.discover_queue_albums_per_similar,
            enrich_ttl=adv.discover_queue_enrich_ttl,
            lastfm_mbid_max_lookups=adv.discover_queue_lastfm_mbid_max_lookups,
        )

    def get_discover_cache_key(
        self, user_id: str, lb_enabled: bool = False, lfm_enabled: bool = False
    ) -> str:
        # Per-user dimension; no source dimension - the unified page builds both
        # services into one response. The enable flags are part of the key (matching
        # Home) so connecting/disconnecting a service busts the cache instead of
        # serving stale unlinked content.
        return f"{DISCOVER_CACHE_KEY}:{user_id}:{lb_enabled}:{lfm_enabled}"

    def get_integration_status(self) -> DiscoverIntegrationStatus:
        return DiscoverIntegrationStatus(
            listenbrainz=self.is_listenbrainz_enabled(),
            jellyfin=self.is_jellyfin_enabled(),
            download_client=self.is_download_client_configured(),
            library=self.is_library_configured(),
            youtube=self.is_youtube_api_enabled(),
            lastfm=self.is_lastfm_enabled(),
        )

    def get_discover_picks_settings(self) -> tuple[float, int]:
        adv = self._preferences.get_advanced_settings()
        return adv.discover_picks_genre_affinity_weight, adv.discover_picks_count
