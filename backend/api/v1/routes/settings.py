import logging
import os
import msgspec
from fastapi import APIRouter, Depends, HTTPException
from api.v1.schemas.settings import (
    UserPreferences, 
    LidarrSettings, 
    LidarrConnectionSettings,
    JellyfinConnectionSettings,
    JellyfinVerifyResponse,
    JellyfinUserInfo,
    NavidromeConnectionSettings,
    ListenBrainzConnectionSettings,
    YouTubeConnectionSettings,
    HomeSettings,
    LidarrVerifyResponse,
    LocalFilesConnectionSettings,
    LocalFilesVerifyResponse,
    LidarrMetadataProfilePreferences,
    LidarrMetadataProfileSummary,
    LastFmConnectionSettings,
    LastFmConnectionSettingsResponse,
    LastFmVerifyResponse,
    ScrobbleSettings,
    PrimaryMusicSourceSettings,
    PlexConnectionSettings,
    PlexVerifyResponse,
    MusicBrainzConnectionSettings,
    SecuritySettings,
    OIDCConnectionSettings,
)
from api.v1.schemas.plex import PlexLibrarySectionInfo
from api.v1.schemas.common import VerifyConnectionResponse
from api.v1.schemas.advanced_settings import AdvancedSettingsFrontend, FrontendCacheTTLs, _is_masked_api_key
from core.dependencies import (
    get_preferences_service,
    get_settings_service,
    get_local_files_service,
    get_oidc_user_auth_service,
)
from services.oidc_user_auth_service import OIDCUserAuthService
from core.exceptions import ConfigurationError, ExternalServiceError
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from middleware import CurrentAdminDep
from services.local_files_service import LocalFilesService
from services.preferences_service import PreferencesService
from services.settings_service import SettingsService

logger = logging.getLogger(__name__)


async def _admin_guard(_: CurrentAdminDep) -> None: ...


router = APIRouter(
    route_class=MsgSpecRoute,
    prefix="/settings",
    tags=["settings"],
    dependencies=[Depends(_admin_guard)],
)


@router.get("/preferences", response_model=UserPreferences)
async def get_preferences(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    return preferences_service.get_preferences()


@router.put("/preferences", response_model=UserPreferences)
async def update_preferences(
    preferences: UserPreferences = MsgSpecBody(UserPreferences),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        preferences_service.save_preferences(preferences)
        total_cleared = await settings_service.clear_caches_for_preference_change()
        return preferences
    except ConfigurationError as e:
        logger.warning(f"Configuration error updating preferences: {e}")
        raise HTTPException(status_code=400, detail="Couldn't save these settings")


@router.get("/lidarr", response_model=LidarrSettings)
async def get_lidarr_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    return preferences_service.get_lidarr_settings()


@router.put("/lidarr", response_model=LidarrSettings)
async def update_lidarr_settings(
    lidarr_settings: LidarrSettings = MsgSpecBody(LidarrSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    try:
        preferences_service.save_lidarr_settings(lidarr_settings)
        return lidarr_settings
    except ConfigurationError as e:
        logger.warning(f"Configuration error updating Lidarr settings: {e}")
        raise HTTPException(status_code=400, detail="Lidarr settings are incomplete or invalid")


@router.get("/cache-ttls", response_model=FrontendCacheTTLs)
async def get_frontend_cache_ttls(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    backend_settings = preferences_service.get_advanced_settings()
    return FrontendCacheTTLs(
        home=backend_settings.frontend_ttl_home,
        discover=backend_settings.frontend_ttl_discover,
        library=backend_settings.frontend_ttl_library,
        recently_added=backend_settings.frontend_ttl_recently_added,
        discover_queue=backend_settings.frontend_ttl_discover_queue,
        search=backend_settings.frontend_ttl_search,
        local_files_sidebar=backend_settings.frontend_ttl_local_files_sidebar,
        jellyfin_sidebar=backend_settings.frontend_ttl_jellyfin_sidebar,
        plex_sidebar=backend_settings.frontend_ttl_plex_sidebar,
        playlist_sources=backend_settings.frontend_ttl_playlist_sources,
        discover_queue_polling_interval=backend_settings.discover_queue_polling_interval,
        discover_queue_auto_generate=backend_settings.discover_queue_auto_generate,
    )


@router.get("/advanced", response_model=AdvancedSettingsFrontend)
async def get_advanced_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    backend_settings = preferences_service.get_advanced_settings()
    return AdvancedSettingsFrontend.from_backend(backend_settings)


@router.put("/advanced", response_model=AdvancedSettingsFrontend)
async def update_advanced_settings(
    settings: AdvancedSettingsFrontend = MsgSpecBody(AdvancedSettingsFrontend),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        backend_settings = settings.to_backend()
        if _is_masked_api_key(backend_settings.audiodb_api_key):
            current = preferences_service.get_advanced_settings()
            backend_settings = msgspec.structs.replace(
                backend_settings, audiodb_api_key=current.audiodb_api_key
            )
        preferences_service.save_advanced_settings(backend_settings)
        await settings_service.on_coverart_settings_changed()
        saved = preferences_service.get_advanced_settings()
        return AdvancedSettingsFrontend.from_backend(saved)
    except ConfigurationError as e:
        logger.warning(f"Configuration error updating advanced settings: {e}")
        raise HTTPException(status_code=400, detail="Couldn't save these settings")
    except ValueError as e:
        logger.warning(f"Validation error updating advanced settings: {e}")
        raise HTTPException(status_code=400, detail="That settings value isn't valid")


@router.get("/lidarr/connection", response_model=LidarrConnectionSettings)
async def get_lidarr_connection(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    return preferences_service.get_lidarr_connection()


@router.put("/lidarr/connection", response_model=LidarrConnectionSettings)
async def update_lidarr_connection(
    settings: LidarrConnectionSettings = MsgSpecBody(LidarrConnectionSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        from repositories.lidarr.base import reset_lidarr_circuit_breaker
        
        preferences_service.save_lidarr_connection(settings)
        reset_lidarr_circuit_breaker()
        await settings_service.on_lidarr_settings_changed()
        return settings
    except ConfigurationError as e:
        logger.warning(f"Configuration error updating Lidarr connection: {e}")
        raise HTTPException(status_code=400, detail="Lidarr connection settings are incomplete or invalid")


@router.post("/lidarr/verify", response_model=LidarrVerifyResponse)
async def verify_lidarr_connection(
    settings: LidarrConnectionSettings = MsgSpecBody(LidarrConnectionSettings),
    settings_service: SettingsService = Depends(get_settings_service),
):
    return await settings_service.verify_lidarr(settings)


@router.get(
    "/lidarr/metadata-profiles",
    response_model=list[LidarrMetadataProfileSummary],
)
async def list_lidarr_metadata_profiles(
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        return await settings_service.list_lidarr_metadata_profiles()
    except ExternalServiceError as e:
        logger.warning(f"Lidarr metadata profiles list failed: {e}")
        raise HTTPException(status_code=502, detail="Couldn't load Lidarr metadata profiles")


@router.get(
    "/lidarr/metadata-profile/preferences",
    response_model=LidarrMetadataProfilePreferences,
)
async def get_lidarr_metadata_profile_preferences(
    profile_id: int | None = None,
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        return await settings_service.get_lidarr_metadata_profile_preferences(
            profile_id=profile_id
        )
    except ExternalServiceError as e:
        logger.warning(f"Lidarr metadata profile fetch failed: {e}")
        raise HTTPException(status_code=502, detail="Couldn't load the Lidarr metadata profile")


@router.put(
    "/lidarr/metadata-profile/preferences",
    response_model=LidarrMetadataProfilePreferences,
)
async def update_lidarr_metadata_profile_preferences(
    preferences: UserPreferences = MsgSpecBody(UserPreferences),
    profile_id: int | None = None,
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        return await settings_service.update_lidarr_metadata_profile(
            preferences, profile_id=profile_id
        )
    except ExternalServiceError as e:
        logger.warning(f"Lidarr metadata profile update failed: {e}")
        raise HTTPException(status_code=502, detail="Couldn't update the Lidarr metadata profile")


@router.get("/jellyfin", response_model=JellyfinConnectionSettings)
async def get_jellyfin_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    return preferences_service.get_jellyfin_connection()


@router.put("/jellyfin", response_model=JellyfinConnectionSettings)
async def update_jellyfin_settings(
    settings: JellyfinConnectionSettings = MsgSpecBody(JellyfinConnectionSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        preferences_service.save_jellyfin_connection(settings)
        await settings_service.on_jellyfin_settings_changed()
        return settings
    except ConfigurationError as e:
        logger.warning(f"Configuration error updating Jellyfin settings: {e}")
        raise HTTPException(status_code=400, detail="Jellyfin settings are incomplete or invalid")


@router.post("/jellyfin/verify", response_model=JellyfinVerifyResponse)
async def verify_jellyfin_connection(
    settings: JellyfinConnectionSettings = MsgSpecBody(JellyfinConnectionSettings),
    settings_service: SettingsService = Depends(get_settings_service),
):
    result = await settings_service.verify_jellyfin(settings)
    users = [JellyfinUserInfo(id=user.id, name=user.name) for user in (result.users or [])] if result.success else []
    return JellyfinVerifyResponse(success=result.success, message=result.message, users=users)


@router.get("/navidrome", response_model=NavidromeConnectionSettings)
async def get_navidrome_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    return preferences_service.get_navidrome_connection()


@router.put("/navidrome", response_model=NavidromeConnectionSettings)
async def update_navidrome_settings(
    settings: NavidromeConnectionSettings = MsgSpecBody(NavidromeConnectionSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        preferences_service.save_navidrome_connection(settings)
        await settings_service.on_navidrome_settings_changed(enabled=settings.enabled)
        return preferences_service.get_navidrome_connection()
    except ConfigurationError as e:
        logger.warning("Configuration error updating Navidrome settings: %s", e)
        raise HTTPException(status_code=400, detail="Navidrome settings are incomplete or invalid")


@router.post("/navidrome/verify", response_model=VerifyConnectionResponse)
async def verify_navidrome_connection(
    settings: NavidromeConnectionSettings = MsgSpecBody(NavidromeConnectionSettings),
    settings_service: SettingsService = Depends(get_settings_service),
):
    result = await settings_service.verify_navidrome(settings)
    return VerifyConnectionResponse(valid=result.valid, message=result.message)


@router.get("/plex", response_model=PlexConnectionSettings)
async def get_plex_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    return preferences_service.get_plex_connection()


@router.put("/plex", response_model=PlexConnectionSettings)
async def update_plex_settings(
    settings: PlexConnectionSettings = MsgSpecBody(PlexConnectionSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        preferences_service.save_plex_connection(settings)
        await settings_service.on_plex_settings_changed(enabled=settings.enabled)
        logger.info("Updated Plex connection settings")
        return preferences_service.get_plex_connection()
    except ConfigurationError as e:
        logger.warning("Configuration error updating Plex settings: %s", e)
        raise HTTPException(status_code=400, detail="Plex settings are incomplete or invalid")


@router.post("/plex/verify", response_model=PlexVerifyResponse)
async def verify_plex_connection(
    settings: PlexConnectionSettings = MsgSpecBody(PlexConnectionSettings),
    settings_service: SettingsService = Depends(get_settings_service),
):
    result = await settings_service.verify_plex(settings)
    libs = [PlexLibrarySectionInfo(key=k, title=t) for k, t in result.libraries]
    return PlexVerifyResponse(valid=result.valid, message=result.message, libraries=libs)


@router.get("/plex/libraries", response_model=list[PlexLibrarySectionInfo])
async def get_plex_libraries(
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        libs = await settings_service.get_plex_libraries()
        return [PlexLibrarySectionInfo(key=k, title=t) for k, t in libs]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Failed to fetch Plex libraries: %s", e)
        raise HTTPException(status_code=502, detail="Could not fetch libraries from Plex")


@router.get("/listenbrainz", response_model=ListenBrainzConnectionSettings)
async def get_listenbrainz_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    return preferences_service.get_listenbrainz_connection()


@router.put("/listenbrainz", response_model=ListenBrainzConnectionSettings)
async def update_listenbrainz_settings(
    settings: ListenBrainzConnectionSettings = MsgSpecBody(ListenBrainzConnectionSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        preferences_service.save_listenbrainz_connection(settings)
        await settings_service.on_listenbrainz_settings_changed()
        return settings
    except ConfigurationError as e:
        logger.warning(f"Configuration error updating ListenBrainz settings: {e}")
        raise HTTPException(status_code=400, detail="ListenBrainz settings are incomplete or invalid")


@router.post("/listenbrainz/verify", response_model=VerifyConnectionResponse)
async def verify_listenbrainz_connection(
    settings: ListenBrainzConnectionSettings = MsgSpecBody(ListenBrainzConnectionSettings),
    settings_service: SettingsService = Depends(get_settings_service),
):
    result = await settings_service.verify_listenbrainz(settings)
    return VerifyConnectionResponse(valid=result.valid, message=result.message)


@router.get("/youtube", response_model=YouTubeConnectionSettings)
async def get_youtube_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    return preferences_service.get_youtube_connection()


@router.put("/youtube", response_model=YouTubeConnectionSettings)
async def update_youtube_settings(
    settings: YouTubeConnectionSettings = MsgSpecBody(YouTubeConnectionSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        preferences_service.save_youtube_connection(settings)
        await settings_service.on_youtube_settings_changed()
        return settings
    except ConfigurationError as e:
        logger.warning(f"Configuration error updating YouTube settings: {e}")
        raise HTTPException(status_code=400, detail="YouTube settings are incomplete or invalid")


@router.post("/youtube/verify", response_model=VerifyConnectionResponse)
async def verify_youtube_connection(
    settings: YouTubeConnectionSettings = MsgSpecBody(YouTubeConnectionSettings),
    settings_service: SettingsService = Depends(get_settings_service),
):
    result = await settings_service.verify_youtube(settings)
    return VerifyConnectionResponse(valid=result.valid, message=result.message)


@router.get("/home", response_model=HomeSettings)
async def get_home_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    return preferences_service.get_home_settings()


@router.put("/home", response_model=HomeSettings)
async def update_home_settings(
    settings: HomeSettings = MsgSpecBody(HomeSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        preferences_service.save_home_settings(settings)
        await settings_service.clear_home_cache()
        return settings
    except ConfigurationError as e:
        logger.warning(f"Configuration error updating home settings: {e}")
        raise HTTPException(status_code=400, detail="Home settings are incomplete or invalid")


@router.get("/local-files", response_model=LocalFilesConnectionSettings)
async def get_local_files_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    return preferences_service.get_local_files_connection()


@router.put("/local-files", response_model=LocalFilesConnectionSettings)
async def update_local_files_settings(
    settings: LocalFilesConnectionSettings = MsgSpecBody(LocalFilesConnectionSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        preferences_service.save_local_files_connection(settings)
        await settings_service.on_local_files_settings_changed()
        return settings
    except ConfigurationError as e:
        logger.warning("Configuration error updating local files settings: %s", e)
        raise HTTPException(status_code=400, detail="Local files settings are incomplete or invalid")


@router.post("/local-files/verify", response_model=LocalFilesVerifyResponse)
async def verify_local_files_connection(
    settings: LocalFilesConnectionSettings = MsgSpecBody(LocalFilesConnectionSettings),
    local_service: LocalFilesService = Depends(get_local_files_service),
) -> LocalFilesVerifyResponse:
    return await local_service.verify_path(settings.music_path)


@router.get("/lastfm", response_model=LastFmConnectionSettingsResponse)
async def get_lastfm_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    settings = preferences_service.get_lastfm_connection()
    return LastFmConnectionSettingsResponse.from_settings(settings)


@router.put("/lastfm", response_model=LastFmConnectionSettingsResponse)
async def update_lastfm_settings(
    settings: LastFmConnectionSettings = MsgSpecBody(LastFmConnectionSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        preferences_service.save_lastfm_connection(settings)
        await settings_service.on_lastfm_settings_changed()
        saved = preferences_service.get_lastfm_connection()
        return LastFmConnectionSettingsResponse.from_settings(saved)
    except ConfigurationError as e:
        logger.warning("Configuration error updating Last.fm settings: %s", e)
        raise HTTPException(status_code=400, detail="Last.fm settings are incomplete or invalid")


@router.post("/lastfm/verify", response_model=LastFmVerifyResponse)
async def verify_lastfm_connection(
    settings: LastFmConnectionSettings = MsgSpecBody(LastFmConnectionSettings),
    settings_service: SettingsService = Depends(get_settings_service),
):
    result = await settings_service.verify_lastfm(settings)
    return LastFmVerifyResponse(valid=result.valid, message=result.message)


@router.get("/scrobble", response_model=ScrobbleSettings)
async def get_scrobble_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    return preferences_service.get_scrobble_settings()


@router.put("/scrobble", response_model=ScrobbleSettings)
async def update_scrobble_settings(
    settings: ScrobbleSettings = MsgSpecBody(ScrobbleSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    try:
        preferences_service.save_scrobble_settings(settings)
        return preferences_service.get_scrobble_settings()
    except ConfigurationError as e:
        logger.warning("Configuration error updating scrobble settings: %s", e)
        raise HTTPException(status_code=400, detail="Scrobbling settings are incomplete or invalid")


@router.get("/primary-source", response_model=PrimaryMusicSourceSettings)
async def get_primary_music_source(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    return preferences_service.get_primary_music_source()


@router.put("/primary-source", response_model=PrimaryMusicSourceSettings)
async def update_primary_music_source(
    settings: PrimaryMusicSourceSettings = MsgSpecBody(PrimaryMusicSourceSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        preferences_service.save_primary_music_source(settings)
        await settings_service.clear_home_cache()
        await settings_service.clear_source_resolution_cache()
        return preferences_service.get_primary_music_source()
    except ConfigurationError as e:
        logger.warning("Configuration error updating primary music source: %s", e)
        raise HTTPException(status_code=400, detail="Invalid primary music source")


@router.get("/musicbrainz", response_model=MusicBrainzConnectionSettings)
async def get_musicbrainz_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
):
    return preferences_service.get_musicbrainz_connection()


@router.put("/musicbrainz", response_model=MusicBrainzConnectionSettings)
async def update_musicbrainz_settings(
    settings: MusicBrainzConnectionSettings = MsgSpecBody(MusicBrainzConnectionSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    try:
        preferences_service.save_musicbrainz_connection(settings)
        await settings_service.on_musicbrainz_settings_changed(settings)
        return settings
    except ConfigurationError as e:
        logger.warning(f"Configuration error updating MusicBrainz settings: {e}")
        raise HTTPException(status_code=400, detail="MusicBrainz settings are incomplete or invalid")


@router.post("/musicbrainz/verify", response_model=VerifyConnectionResponse)
async def verify_musicbrainz_connection(
    settings: MusicBrainzConnectionSettings = MsgSpecBody(MusicBrainzConnectionSettings),
    settings_service: SettingsService = Depends(get_settings_service),
):
    result = await settings_service.verify_musicbrainz(settings)
    return VerifyConnectionResponse(valid=result.valid, message=result.message)


@router.get("/security", response_model=SecuritySettings)
async def get_security_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
) -> SecuritySettings:
    return preferences_service.get_security_settings()


@router.put("/security", response_model=SecuritySettings)
async def update_security_settings(
    settings: SecuritySettings = MsgSpecBody(SecuritySettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
) -> SecuritySettings:
    try:
        preferences_service.save_security_settings(settings)
        return settings
    except ConfigurationError as e:
        logger.warning(f"Configuration error updating security settings: {e}")
        raise HTTPException(status_code=400, detail="Could not save security settings")


@router.post("/security/verify-hibp", response_model=VerifyConnectionResponse)
async def verify_hibp_local_file(
    settings: SecuritySettings = MsgSpecBody(SecuritySettings),
) -> VerifyConnectionResponse:
    """Validate a user-supplied HIBP local database path."""
    path = (settings.hibp_local_path or "").strip()
    if not path:
        return VerifyConnectionResponse(valid=False, message="No path provided.")

    if not os.path.isfile(path):
        return VerifyConnectionResponse(valid=False, message=f"File not found: {path}")

    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            first_line = fh.readline().decode("ascii", errors="ignore").strip()

        if not first_line or ":" not in first_line:
            return VerifyConnectionResponse(
                valid=False,
                message="File does not appear to be a valid HIBP hash list (unexpected format).",
            )

        parts = first_line.split(":", 1)
        if len(parts[0]) != 40 or not parts[0].isalnum():
            return VerifyConnectionResponse(
                valid=False,
                message="File does not appear to be a valid HIBP hash list (expected 40-char SHA-1 hash).",
            )

        def _fmt_size(b: int) -> str:
            for unit in ("B", "KB", "MB", "GB"):
                if b < 1024:
                    return f"{b:.1f} {unit}"
                b //= 1024
            return f"{b:.1f} TB"

        return VerifyConnectionResponse(
            valid=True,
            message=f"File looks valid. Size: {_fmt_size(size)}.",
        )
    except OSError as e:
        return VerifyConnectionResponse(valid=False, message=f"Could not read file: {e}")


@router.get("/oidc", response_model=OIDCConnectionSettings)
async def get_oidc_settings(
    preferences_service: PreferencesService = Depends(get_preferences_service),
) -> OIDCConnectionSettings:
    return preferences_service.get_oidc_connection()


@router.put("/oidc", response_model=OIDCConnectionSettings)
async def update_oidc_settings(
    settings: OIDCConnectionSettings = MsgSpecBody(OIDCConnectionSettings),
    preferences_service: PreferencesService = Depends(get_preferences_service),
) -> OIDCConnectionSettings:
    try:
        preferences_service.save_oidc_connection(settings)
        return preferences_service.get_oidc_connection()
    except ConfigurationError as e:
        logger.warning(f"Configuration error updating OIDC settings: {e}")
        raise HTTPException(status_code=400, detail="OIDC settings are incomplete or invalid")


@router.post("/oidc/verify", response_model=VerifyConnectionResponse)
async def verify_oidc_connection(
    settings: OIDCConnectionSettings = MsgSpecBody(OIDCConnectionSettings),
    oidc_auth: OIDCUserAuthService = Depends(get_oidc_user_auth_service),
) -> VerifyConnectionResponse:
    valid, message = await oidc_auth.verify(settings)
    return VerifyConnectionResponse(valid=valid, message=message)
