from typing import Literal

import msgspec

from api.v1.schemas.plex import PlexLibrarySectionInfo
from infrastructure.msgspec_fastapi import AppStruct

LASTFM_SECRET_MASK = "••••••••"


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return LASTFM_SECRET_MASK
    return LASTFM_SECRET_MASK + value[-4:]


class LastFmConnectionSettings(AppStruct):
    api_key: str = ""
    shared_secret: str = ""
    session_key: str = ""
    username: str = ""
    enabled: bool = False


class LastFmConnectionSettingsResponse(AppStruct):
    api_key: str = ""
    shared_secret: str = ""
    session_key: str = ""
    username: str = ""
    enabled: bool = False

    @classmethod
    def from_settings(cls, settings: LastFmConnectionSettings) -> "LastFmConnectionSettingsResponse":
        return cls(
            api_key=settings.api_key,
            shared_secret=_mask_secret(settings.shared_secret),
            session_key=_mask_secret(settings.session_key),
            username=settings.username,
            enabled=settings.enabled,
        )


class LastFmVerifyResponse(AppStruct):
    valid: bool
    message: str


class LastFmAuthTokenResponse(AppStruct):
    token: str
    auth_url: str


class LastFmAuthSessionRequest(AppStruct):
    token: str


class LastFmAuthSessionResponse(AppStruct):
    success: bool
    message: str
    username: str = ""


class UserPreferences(AppStruct):
    primary_types: list[str] = msgspec.field(default_factory=lambda: ["album", "ep", "single"])
    secondary_types: list[str] = msgspec.field(default_factory=lambda: ["studio"])
    release_statuses: list[str] = msgspec.field(default_factory=lambda: ["official"])


class LidarrConnectionSettings(AppStruct):
    lidarr_url: str = "http://lidarr:8686"
    lidarr_api_key: str = ""
    quality_profile_id: int = 1
    metadata_profile_id: int = 1
    root_folder_path: str = "/music"

    def __post_init__(self) -> None:
        self.lidarr_url = self.lidarr_url.rstrip("/")
        if self.quality_profile_id < 1:
            raise msgspec.ValidationError("quality_profile_id must be >= 1")
        if self.metadata_profile_id < 1:
            raise msgspec.ValidationError("metadata_profile_id must be >= 1")


class JellyfinConnectionSettings(AppStruct):
    jellyfin_url: str = "http://jellyfin:8096"
    api_key: str = ""
    user_id: str = ""
    enabled: bool = False

    def __post_init__(self) -> None:
        self.jellyfin_url = self.jellyfin_url.rstrip("/")


class OIDCConnectionSettings(msgspec.Struct):
    enabled: bool = False
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    scopes: str = "openid email profile"
    redirect_uri: str = ""


NAVIDROME_PASSWORD_MASK = "********"
PLEX_TOKEN_MASK = "plex****"


class NavidromeConnectionSettings(AppStruct):
    navidrome_url: str = ""
    username: str = ""
    password: str = ""
    enabled: bool = False

    def __post_init__(self) -> None:
        self.navidrome_url = self.navidrome_url.rstrip("/") if self.navidrome_url else ""


class PlexConnectionSettings(AppStruct):
    plex_url: str = ""
    plex_token: str = ""
    enabled: bool = False
    music_library_ids: list[str] = []
    scrobble_to_plex: bool = True

    def __post_init__(self) -> None:
        self.plex_url = self.plex_url.rstrip("/") if self.plex_url else ""


class PlexVerifyResponse(AppStruct):
    valid: bool
    message: str
    libraries: list[PlexLibrarySectionInfo] = []


class PlexOAuthPinResponse(AppStruct):
    pin_id: int
    pin_code: str
    auth_url: str


class PlexOAuthPollResponse(AppStruct):
    completed: bool
    auth_token: str = ""


class JellyfinUserInfo(AppStruct):
    id: str
    name: str


class JellyfinVerifyResponse(AppStruct):
    success: bool
    message: str
    users: list[JellyfinUserInfo] = []


class ListenBrainzConnectionSettings(AppStruct):
    username: str = ""
    user_token: str = ""
    enabled: bool = False


class YouTubeConnectionSettings(AppStruct):
    api_key: str = ""
    enabled: bool = False
    api_enabled: bool = False
    daily_quota_limit: int = 80

    def __post_init__(self) -> None:
        if self.daily_quota_limit < 1 or self.daily_quota_limit > 10000:
            raise msgspec.ValidationError("daily_quota_limit must be between 1 and 10000")

    def has_valid_api_key(self) -> bool:
        return bool(self.api_key and self.api_key.strip())


class HomeSettings(AppStruct):
    cache_ttl_trending: int = 3600
    cache_ttl_personal: int = 300
    show_whats_hot: bool = True
    show_globally_trending: bool = True

    def __post_init__(self) -> None:
        if self.cache_ttl_trending < 300 or self.cache_ttl_trending > 86400:
            raise msgspec.ValidationError("cache_ttl_trending must be between 300 and 86400")
        if self.cache_ttl_personal < 60 or self.cache_ttl_personal > 3600:
            raise msgspec.ValidationError("cache_ttl_personal must be between 60 and 3600")


class LocalFilesConnectionSettings(AppStruct):
    enabled: bool = False
    music_path: str = "/music"
    lidarr_root_path: str = "/music"


class LocalFilesVerifyResponse(AppStruct):
    success: bool
    message: str
    track_count: int = 0


class LidarrSettings(AppStruct):
    sync_frequency: Literal["manual", "5min", "10min", "30min", "1hr", "6hr", "12hr", "24hr", "3d", "7d"] = "24hr"
    last_sync: int | None = None
    last_sync_success: bool = True


class LidarrProfileSummary(AppStruct):
    id: int
    name: str


class LidarrRootFolderSummary(AppStruct):
    id: str
    path: str


class LidarrVerifyResponse(AppStruct):
    success: bool
    message: str
    quality_profiles: list[LidarrProfileSummary] = []
    metadata_profiles: list[LidarrProfileSummary] = []
    root_folders: list[LidarrRootFolderSummary] = []


class LidarrMetadataProfileSummary(AppStruct):
    id: int
    name: str


class ScrobbleSettings(AppStruct):
    scrobble_to_lastfm: bool = False
    scrobble_to_listenbrainz: bool = False


class PrimaryMusicSourceSettings(AppStruct):
    source: Literal["listenbrainz", "lastfm"] = "listenbrainz"


_OFFICIAL_MB_RATE_LIMIT = 1.0
_OFFICIAL_MB_CONCURRENT_SEARCHES = 6


def is_official_musicbrainz(url: str) -> bool:
    """Check if the URL points to the official MusicBrainz API."""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url.strip().rstrip("/"))
        hostname = (parsed.hostname or "").lower()
        return hostname in ("musicbrainz.org", "www.musicbrainz.org")
    except (ValueError, AttributeError):
        return False


class SecuritySettings(AppStruct):
    # Password security
    hibp_check: bool = True
    # Path to a local copy of the HIBP "Pwned Passwords" sorted-by-hash file.
    # When set and the file exists, used instead of the API, no outbound calls.
    hibp_local_path: str = ""

    # HSTS: only enable when serving over HTTPS
    hsts_max_age: int = 0            # seconds; 0 = disabled
    hsts_include_subdomains: bool = False
    hsts_preload: bool = False


class MusicBrainzConnectionSettings(AppStruct):
    api_url: str = "https://musicbrainz.org/ws/2"
    rate_limit: float = 1.0
    concurrent_searches: int = 6

    def __post_init__(self) -> None:
        self.api_url = self.api_url.strip()
        if not self.api_url or not self.api_url.startswith(("http://", "https://")):
            self.api_url = "https://musicbrainz.org/ws/2"
        self.api_url = self.api_url.rstrip("/")
        if is_official_musicbrainz(self.api_url):
            self.rate_limit = min(self.rate_limit, _OFFICIAL_MB_RATE_LIMIT)
            self.concurrent_searches = min(self.concurrent_searches, _OFFICIAL_MB_CONCURRENT_SEARCHES)
        if self.rate_limit < 0.1 or self.rate_limit > 50.0:
            raise msgspec.ValidationError("rate_limit must be between 0.1 and 50.0")
        if self.concurrent_searches < 1 or self.concurrent_searches > 30:
            raise msgspec.ValidationError("concurrent_searches must be between 1 and 30")


class LidarrMetadataProfilePreferences(AppStruct):
    profile_id: int
    profile_name: str
    primary_types: list[str] = []
    secondary_types: list[str] = []
    release_statuses: list[str] = []
