import logging
import threading
from typing import Optional, TypeVar, Type
from typing import Any

import msgspec
from api.v1.schemas.settings import (
    UserPreferences,
    LidarrSettings,
    LidarrConnectionSettings,
    JellyfinConnectionSettings,
    ListenBrainzConnectionSettings,
    OIDCConnectionSettings,
    YouTubeConnectionSettings,
    HomeSettings,
    LocalFilesConnectionSettings,
    LastFmConnectionSettings,
    ScrobbleSettings,
    PrimaryMusicSourceSettings,
    LASTFM_SECRET_MASK,
    NavidromeConnectionSettings,
    NAVIDROME_PASSWORD_MASK,
    PlexConnectionSettings,
    PLEX_TOKEN_MASK,
    MusicBrainzConnectionSettings,
    SecuritySettings,
)
from api.v1.schemas.profile import ProfileSettings
from api.v1.schemas.advanced_settings import AdvancedSettings
from core.config import Settings
from core.exceptions import ConfigurationError
from infrastructure.file_utils import atomic_write_json, read_json
from infrastructure.serialization import to_jsonable

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=msgspec.Struct)


class PreferencesService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._config_path = settings.config_file_path
        self._config_cache: Optional[dict] = None
        self._cache_lock = threading.RLock()
        self._migrate_musicbrainz_settings()
        self._ensure_instance_id()

    def _ensure_instance_id(self) -> None:
        """Generate a stable instance ID on first run."""
        config = self._load_config()
        if config.get("instance_id"):
            return
        import uuid
        instance_id = str(uuid.uuid4())
        config = self._load_config().copy()
        config["instance_id"] = instance_id
        self._save_config(config)
        logger.info("Generated new instance ID: %s", instance_id)

    def get_instance_id(self) -> str:
        config = self._load_config()
        return config.get("instance_id", "unknown")

    def _load_config(self) -> dict:
        with self._cache_lock:
            if self._config_cache is not None:
                return self._config_cache

            if not self._config_path.exists():
                self._config_cache = {}
                return self._config_cache

            try:
                loaded = read_json(self._config_path, default={})
                self._config_cache = loaded if isinstance(loaded, dict) else {}
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to load config: {e}")
                self._config_cache = {}

            return self._config_cache

    def _save_config(self, config: dict) -> None:
        with self._cache_lock:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self._config_path, config)
            self._config_cache = config

    def _get_section(self, key: str, model: Type[T], default_factory: Optional[callable] = None) -> T:
        config = self._load_config()
        data = config.get(key, {})
        try:
            if not (isinstance(model, type) and issubclass(model, msgspec.Struct)):
                raise TypeError(f"Preferences section model must be msgspec.Struct, got {model!r}")

            if data:
                return msgspec.convert(data, type=model)
            return default_factory() if default_factory else model()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to parse {key}: {e}")
            return default_factory() if default_factory else model()

    def _save_section(self, key: str, value: Any) -> None:
        config = self._load_config().copy()
        config[key] = to_jsonable(value)
        self._save_config(config)

    def get_preferences(self) -> UserPreferences:
        return self._get_section("user_preferences", UserPreferences)

    def save_preferences(self, preferences: UserPreferences) -> None:
        try:
            self._save_section("user_preferences", preferences)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to save preferences: {e}")
            raise ConfigurationError(f"Failed to save preferences: {e}")

    def get_lidarr_settings(self) -> LidarrSettings:
        return self._get_section("lidarr_settings", LidarrSettings)

    def save_lidarr_settings(self, lidarr_settings: LidarrSettings) -> None:
        try:
            self._save_section("lidarr_settings", lidarr_settings)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to save Lidarr settings: {e}")
            raise ConfigurationError(f"Failed to save Lidarr settings: {e}")

    def get_advanced_settings(self) -> AdvancedSettings:
        return self._get_section("advanced_settings", AdvancedSettings)

    def save_advanced_settings(self, advanced_settings: AdvancedSettings) -> None:
        try:
            self._save_section("advanced_settings", advanced_settings)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to save advanced settings: {e}")
            raise ConfigurationError(f"Failed to save advanced settings: {e}")

    def get_lidarr_connection(self) -> LidarrConnectionSettings:
        config = self._load_config()
        return LidarrConnectionSettings(
            lidarr_url=config.get("lidarr_url", self._settings.lidarr_url),
            lidarr_api_key=config.get("lidarr_api_key", self._settings.lidarr_api_key),
            quality_profile_id=config.get("quality_profile_id", self._settings.quality_profile_id),
            metadata_profile_id=config.get("metadata_profile_id", self._settings.metadata_profile_id),
            root_folder_path=config.get("root_folder_path", self._settings.root_folder_path),
        )

    def save_lidarr_connection(self, settings: LidarrConnectionSettings) -> None:
        try:
            config = self._load_config().copy()
            config.update({
                "lidarr_url": settings.lidarr_url,
                "lidarr_api_key": settings.lidarr_api_key,
                "quality_profile_id": settings.quality_profile_id,
                "metadata_profile_id": settings.metadata_profile_id,
                "root_folder_path": settings.root_folder_path,
            })
            self._save_config(config)

            self._settings.lidarr_url = settings.lidarr_url
            self._settings.lidarr_api_key = settings.lidarr_api_key
            self._settings.quality_profile_id = settings.quality_profile_id
            self._settings.metadata_profile_id = settings.metadata_profile_id
            self._settings.root_folder_path = settings.root_folder_path
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to save Lidarr connection settings: {e}")
            raise ConfigurationError(f"Failed to save Lidarr connection settings: {e}")

    def get_jellyfin_connection(self) -> JellyfinConnectionSettings:
        config = self._load_config()
        jellyfin_data = config.get("jellyfin_settings", {})
        return JellyfinConnectionSettings(
            jellyfin_url=jellyfin_data.get("jellyfin_url", config.get("jellyfin_url", self._settings.jellyfin_url)),
            api_key=jellyfin_data.get("api_key", ""),
            user_id=jellyfin_data.get("user_id", ""),
            enabled=jellyfin_data.get("enabled", False),
        )

    def save_jellyfin_connection(self, settings: JellyfinConnectionSettings) -> None:
        try:
            config = self._load_config().copy()
            config["jellyfin_url"] = settings.jellyfin_url
            config["jellyfin_settings"] = {
                "jellyfin_url": settings.jellyfin_url,
                "api_key": settings.api_key,
                "user_id": settings.user_id,
                "enabled": settings.enabled,
            }
            self._save_config(config)

            self._settings.jellyfin_url = settings.jellyfin_url
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to save Jellyfin connection settings: {e}")
            raise ConfigurationError(f"Failed to save Jellyfin connection settings: {e}")

    def get_navidrome_connection(self) -> NavidromeConnectionSettings:
        config = self._load_config()
        nd_data = config.get("navidrome_settings", {})
        password = nd_data.get("password", "")
        return NavidromeConnectionSettings(
            navidrome_url=nd_data.get("navidrome_url", ""),
            username=nd_data.get("username", ""),
            password=NAVIDROME_PASSWORD_MASK if password else "",
            enabled=nd_data.get("enabled", False),
        )

    def get_navidrome_connection_raw(self) -> NavidromeConnectionSettings:
        config = self._load_config()
        nd_data = config.get("navidrome_settings", {})
        return NavidromeConnectionSettings(
            navidrome_url=nd_data.get("navidrome_url", ""),
            username=nd_data.get("username", ""),
            password=nd_data.get("password", ""),
            enabled=nd_data.get("enabled", False),
        )

    def save_navidrome_connection(self, settings: NavidromeConnectionSettings) -> None:
        try:
            config = self._load_config().copy()
            current_data = config.get("navidrome_settings", {})

            password = settings.password
            if password == NAVIDROME_PASSWORD_MASK:
                password = current_data.get("password", "")

            config["navidrome_settings"] = {
                "navidrome_url": settings.navidrome_url,
                "username": settings.username,
                "password": password,
                "enabled": settings.enabled,
            }
            self._save_config(config)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to save Navidrome connection settings: %s", e)
            raise ConfigurationError(f"Failed to save Navidrome connection settings: {e}")

    def get_plex_connection(self) -> PlexConnectionSettings:
        config = self._load_config()
        plex_data = config.get("plex_settings", {})
        settings = PlexConnectionSettings(
            plex_url=plex_data.get("plex_url", ""),
            plex_token=plex_data.get("plex_token", ""),
            enabled=plex_data.get("enabled", False),
            music_library_ids=plex_data.get("music_library_ids", []),
            scrobble_to_plex=plex_data.get("scrobble_to_plex", True),
        )
        if settings.plex_token:
            settings.plex_token = PLEX_TOKEN_MASK
        return settings

    def get_plex_connection_raw(self) -> PlexConnectionSettings:
        config = self._load_config()
        plex_data = config.get("plex_settings", {})
        return PlexConnectionSettings(
            plex_url=plex_data.get("plex_url", ""),
            plex_token=plex_data.get("plex_token", ""),
            enabled=plex_data.get("enabled", False),
            music_library_ids=plex_data.get("music_library_ids", []),
            scrobble_to_plex=plex_data.get("scrobble_to_plex", True),
        )

    def save_plex_connection(self, settings: PlexConnectionSettings) -> None:
        try:
            config = self._load_config().copy()
            current_data = config.get("plex_settings", {})

            token = settings.plex_token
            if token == PLEX_TOKEN_MASK:
                token = current_data.get("plex_token", "")

            config["plex_settings"] = {
                "plex_url": settings.plex_url,
                "plex_token": token,
                "enabled": settings.enabled,
                "music_library_ids": settings.music_library_ids,
                "scrobble_to_plex": settings.scrobble_to_plex,
            }
            self._save_config(config)
            logger.info("Saved Plex connection settings to %s", self._config_path)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to save Plex connection settings: %s", e)
            raise ConfigurationError(f"Failed to save Plex connection settings: {e}")

    def get_listenbrainz_connection(self) -> ListenBrainzConnectionSettings:
        config = self._load_config()
        lb_data = config.get("listenbrainz_settings", {})
        return ListenBrainzConnectionSettings(
            username=lb_data.get("username", ""),
            user_token=lb_data.get("user_token", ""),
            enabled=lb_data.get("enabled", False),
        )

    def save_listenbrainz_connection(self, settings: ListenBrainzConnectionSettings) -> None:
        try:
            config = self._load_config().copy()
            config["listenbrainz_settings"] = {
                "username": settings.username,
                "user_token": settings.user_token,
                "enabled": settings.enabled,
            }
            self._save_config(config)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to save ListenBrainz connection settings: {e}")
            raise ConfigurationError(f"Failed to save ListenBrainz connection settings: {e}")

    def get_youtube_connection(self) -> YouTubeConnectionSettings:
        config = self._load_config()
        yt_data = config.get("youtube_settings", {})
        api_key = str(yt_data.get("api_key") or "")
        enabled = yt_data.get("enabled", False)
        # Auto-migrate: existing setups with enabled+api_key get api_enabled=True
        if "api_enabled" not in yt_data and enabled and api_key.strip():
            api_enabled = True
        else:
            api_enabled = yt_data.get("api_enabled", False)
        return YouTubeConnectionSettings(
            api_key=api_key,
            enabled=enabled,
            api_enabled=api_enabled,
            daily_quota_limit=yt_data.get("daily_quota_limit", 80),
        )

    def save_youtube_connection(self, settings: YouTubeConnectionSettings) -> None:
        try:
            config = self._load_config().copy()
            config["youtube_settings"] = {
                "api_key": settings.api_key.strip(),
                "enabled": settings.enabled,
                "api_enabled": settings.api_enabled,
                "daily_quota_limit": settings.daily_quota_limit,
            }
            self._save_config(config)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to save YouTube connection settings: {e}")
            raise ConfigurationError(f"Failed to save YouTube connection settings: {e}")

    def get_home_settings(self) -> HomeSettings:
        return self._get_section("home_settings", HomeSettings)

    def save_home_settings(self, settings: HomeSettings) -> None:
        try:
            self._save_section("home_settings", settings)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to save home settings: {e}")
            raise ConfigurationError(f"Failed to save home settings: {e}")

    def get_local_files_connection(self) -> LocalFilesConnectionSettings:
        return self._get_section("local_files_settings", LocalFilesConnectionSettings)

    def save_local_files_connection(self, settings: LocalFilesConnectionSettings) -> None:
        try:
            self._save_section("local_files_settings", settings)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to save local files settings: %s", e)
            raise ConfigurationError(f"Failed to save local files settings: {e}")

    def get_lastfm_connection(self) -> LastFmConnectionSettings:
        return self._get_section("lastfm_settings", LastFmConnectionSettings)

    def save_lastfm_connection(self, settings: LastFmConnectionSettings) -> None:
        try:
            current = self.get_lastfm_connection()

            api_key = settings.api_key.strip()
            shared_secret = settings.shared_secret
            if shared_secret.startswith(LASTFM_SECRET_MASK):
                shared_secret = current.shared_secret
            else:
                shared_secret = shared_secret.strip()

            session_key = settings.session_key
            if session_key.startswith(LASTFM_SECRET_MASK):
                session_key = current.session_key
            else:
                session_key = session_key.strip()

            username = settings.username.strip()
            enabled = settings.enabled
            if not api_key or not shared_secret:
                enabled = False
                session_key = ""
                username = ""

            resolved = LastFmConnectionSettings(
                api_key=api_key,
                shared_secret=shared_secret,
                session_key=session_key,
                username=username,
                enabled=enabled,
            )
            self._save_section("lastfm_settings", resolved)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to save Last.fm connection settings: %s", e)
            raise ConfigurationError(f"Failed to save Last.fm connection settings: {e}")

    def is_lastfm_enabled(self) -> bool:
        settings = self.get_lastfm_connection()
        return settings.enabled and bool(settings.api_key) and bool(settings.shared_secret)

    def get_scrobble_settings(self) -> ScrobbleSettings:
        return self._get_section("scrobble_settings", ScrobbleSettings)

    def save_scrobble_settings(self, settings: ScrobbleSettings) -> None:
        try:
            self._save_section("scrobble_settings", settings)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to save scrobble settings: %s", e)
            raise ConfigurationError(f"Failed to save scrobble settings: {e}")

    def get_primary_music_source(self) -> PrimaryMusicSourceSettings:
        return self._get_section("primary_music_source", PrimaryMusicSourceSettings)

    def save_primary_music_source(self, settings: PrimaryMusicSourceSettings) -> None:
        try:
            self._save_section("primary_music_source", settings)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to save primary music source: %s", e)
            raise ConfigurationError(f"Failed to save primary music source: {e}")

    def get_profile_settings(self) -> ProfileSettings:
        return self._get_section("profile_settings", ProfileSettings)

    def save_profile_settings(self, settings: ProfileSettings) -> None:
        try:
            self._save_section("profile_settings", settings)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to save profile settings: %s", e)
            raise ConfigurationError(f"Failed to save profile settings: {e}")

    def get_setting(self, key: str) -> Any:
        config = self._load_config()
        internal = config.get("_internal", {})
        return internal.get(key)

    def save_setting(self, key: str, value: Any) -> None:
        config = self._load_config().copy()
        internal = config.get("_internal", {}).copy()
        if value is None:
            internal.pop(key, None)
        else:
            internal[key] = value
        config["_internal"] = internal
        self._save_config(config)

    def get_or_create_setting(self, key: str, factory: Any) -> Any:
        """Atomically get or create an internal setting under the cache lock."""
        with self._cache_lock:
            config = self._load_config()
            internal = config.get("_internal", {})
            value = internal.get(key)
            if value:
                return value
            value = factory() if callable(factory) else factory
            config = config.copy()
            internal = internal.copy()
            internal[key] = value
            config["_internal"] = internal
            self._save_config(config)
            return value

    def get_musicbrainz_connection(self) -> MusicBrainzConnectionSettings:
        return self._get_section("musicbrainz_settings", MusicBrainzConnectionSettings)

    def save_musicbrainz_connection(self, settings: MusicBrainzConnectionSettings) -> None:
        try:
            settings.api_url = settings.api_url.rstrip("/")
            self._save_section("musicbrainz_settings", settings)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to save MusicBrainz settings: {e}")
            raise ConfigurationError(f"Failed to save MusicBrainz settings: {e}")

    def _migrate_musicbrainz_settings(self) -> None:
        """One-time migration of musicbrainz_concurrent_searches from advanced_settings."""
        try:
            config = self._load_config()
            if config.get("musicbrainz_settings") is not None:
                return

            advanced_data = config.get("advanced_settings", {})
            old_value = advanced_data.get("musicbrainz_concurrent_searches")
            if old_value is not None:
                settings = MusicBrainzConnectionSettings(concurrent_searches=int(old_value))
                self._save_section("musicbrainz_settings", settings)
                logger.info(f"Migrated musicbrainz_concurrent_searches={old_value} to musicbrainz_settings")
        except Exception:  # noqa: BLE001
            logger.warning("Failed to migrate musicbrainz_concurrent_searches, using defaults")
            self._save_section("musicbrainz_settings", MusicBrainzConnectionSettings())
    
    def get_oidc_connection(self) -> OIDCConnectionSettings:
        return self._get_section("oidc_settings", OIDCConnectionSettings)

    def save_oidc_connection(self, settings: OIDCConnectionSettings) -> None:
        try:
            self._save_section("oidc_settings", settings)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to save OIDC settings: {e}")
            raise ConfigurationError(f"Failed to save OIDC settings")

    def get_security_settings(self) -> SecuritySettings:
        return self._get_section("security_settings", SecuritySettings)

    def save_security_settings(self, settings: SecuritySettings) -> None:
        try:
            self._save_section("security_settings", settings)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to save security settings: {e}")
            raise ConfigurationError(f"Failed to save security settings")
